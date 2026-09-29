"""Brief service tests (T14): acceptance 4-6 and 9 with FakeLLM/FakeMemoryService, no network."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from sqlmodel import Session, select

from app.config import settings
from app.core.errors import LLMTimeoutError, MemoryUnavailableError
from app.db import repository
from app.db.models import BriefRecord, Commitment, Meeting
from app.memory.memory_service import MemoryService, MentalModelText
from app.schemas.brief import Brief, BriefDraft, BriefItem, SectionKey, Severity, SourceType
from app.schemas.enums import CommitmentStatus, FactKind, Owner
from app.schemas.memory import MemoryHit, ReflectResult
from app.services import brief as brief_module
from app.services.brief import (
    BRIEF_LLM_TIMEOUT_SECONDS,
    default_brief_llm,
    first_line_spoken_by,
    generate_brief,
    get_cached_brief,
    load_persona,
    render_brief_prompt,
)
from tests.fakes.fake_llm import FakeLLM
from tests.unit.brief_world import (
    ANITA_M2_LINE,
    DECK_QUOTE,
    M6,
    RAHUL_M4_LINE,
    ScriptedLLM,
    World,
    evidence_ids,
    good_draft,
    item,
    make_world,
    queue_objections,
)


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    yield from make_world(tmp_path)


def all_items(brief: Brief) -> list[BriefItem]:
    return [i for s in brief.sections for i in s.items]


def section(brief: Brief, key: SectionKey) -> list[BriefItem]:
    return next((s.items for s in brief.sections if s.key == key), [])


async def make(
    w: World,
    build: Any = good_draft,
    mode: str = "memory",
    memory: MemoryService | None = None,
) -> tuple[Brief, ScriptedLLM]:
    llm = ScriptedLLM(build)
    brief = await generate_brief(
        M6,
        mode,
        llm=llm,
        memory=memory or w.memory,
        session_factory=w.session_factory,  # type: ignore[arg-type]
    )
    return brief, llm


# ---- story beats (memory mode) ---------------------------------------------------------


@pytest.mark.parametrize("llm_severity", [Severity.info, Severity.warning, Severity.critical])
async def test_b1_overdue_deck_is_critical_and_cited_to_m4(
    world: World,
    llm_severity: Severity,
) -> None:
    brief, _ = await make(world, lambda p: good_draft(p, llm_severity))

    (deck,) = [i for i in section(brief, SectionKey.open_commitments) if "deck" in i.text.lower()]
    assert deck.severity == Severity.critical  # forced in code whatever the LLM said
    (citation,) = deck.citations
    assert citation.source_type == SourceType.ledger
    assert citation.meeting_id == "m4_finedge"
    assert citation.meeting_date == date(2026, 8, 27)
    assert citation.quote == DECK_QUOTE
    assert citation.label == "Ledger, Call on Aug 27, 2026"


async def test_overdue_item_appended_when_llm_omits_it(world: World) -> None:
    def no_deck(prompt: str) -> BriefDraft:
        return BriefDraft(
            sections={
                SectionKey.watch_outs: [
                    item("DataHawk is cheaper", evidence_ids(prompt, "DataHawk"))
                ]
            }
        )

    brief, _ = await make(world, no_deck)

    (forced,) = section(brief, SectionKey.open_commitments)
    assert forced.severity == Severity.critical
    assert "pricing deck" in forced.text
    assert forced.citations[0].meeting_id == "m4_finedge"
    assert forced.citations[0].quote == DECK_QUOTE
    assert forced.contact_ids == ["c_rahul"]


async def test_closed_and_not_overdue_commitments_are_not_forced(world: World) -> None:
    with Session(world.engine) as s:
        deck = s.get(Commitment, "cm_deck")
        assert deck is not None
        deck.due_date = date(2026, 10, 1)  # not overdue on 2026-09-28
        s.add(deck)
        s.commit()

    brief, _ = await make(world, lambda p: BriefDraft(sections={}))

    assert section(brief, SectionKey.open_commitments) == []


async def test_b3_personal_touchpoint_cited_to_m1_or_m5(world: World) -> None:
    brief, llm = await make(world)

    (touch,) = section(brief, SectionKey.personal_touchpoints)
    assert {c.meeting_id for c in touch.citations} <= {"m1_finedge", "m5_finedge"}
    assert {c.meeting_id for c in touch.citations} == {"m1_finedge", "m5_finedge"}
    # The observation hit (empty metadata, tag-only meeting) resolved to M5 with its date.
    m5 = next(c for c in touch.citations if c.meeting_id == "m5_finedge")
    assert m5.meeting_date == date(2026, 9, 15)
    assert m5.quote and "Ananya" in m5.quote
    assert touch.contact_ids == ["c_rahul"]
    assert "Ananya" in llm.calls[0].prompt


async def test_b4_competitor_watch_out_cited_to_m3(world: World) -> None:
    brief, _ = await make(world)

    (watch,) = section(brief, SectionKey.watch_outs)
    assert watch.text == "FinEdge has looked at DataHawk."
    assert [c.meeting_id for c in watch.citations] == ["m3_finedge"]
    assert watch.citations[0].meeting_date == date(2026, 8, 12)
    assert watch.severity == Severity.warning  # floor for watch_outs


async def test_repeated_same_meeting_competitor_objection_is_dropped(world: World) -> None:
    def draft(prompt: str) -> BriefDraft:
        return BriefDraft(
            sections={
                SectionKey.unresolved_objections: [
                    item(
                        "Karan still has concerns about DataHawk.",
                        evidence_ids(prompt, "DataHawk"),
                    )
                ]
            }
        )

    brief, _ = await make(world, draft)

    assert section(brief, SectionKey.unresolved_objections) == []
    (watch_out,) = section(brief, SectionKey.watch_outs)
    assert watch_out.text == "FinEdge has looked at DataHawk."
    assert watch_out.citations[0].meeting_id == "m3_finedge"


async def test_overdue_commitments_keep_one_red_group_us_and_mark_customer_info(
    world: World,
) -> None:
    with Session(world.engine) as s:
        s.add(
            Commitment(
                id="cm_us_second",
                account_id="acc_finedge",
                meeting_id="m4_finedge",
                owner=Owner.us,
                contact_id="c_rahul",
                text="Send rollout plan",
                due_date=date(2026, 9, 10),
                status=CommitmentStatus.open,
                source_quote="I will send the rollout plan",
            )
        )
        s.add(
            Commitment(
                id="cm_customer",
                account_id="acc_finedge",
                meeting_id="m4_finedge",
                owner=Owner.them,
                contact_id="c_rahul",
                text="Provide the pipeline shortlist",
                due_date=date(2026, 9, 12),
                status=CommitmentStatus.open,
                source_quote="We will provide the shortlist",
            )
        )
        s.commit()

    brief, _ = await make(world, lambda p: BriefDraft(sections={}))
    commitments = section(brief, SectionKey.open_commitments)
    critical = [entry for entry in all_items(brief) if entry.severity == Severity.critical]
    assert len(critical) == 1
    assert "pricing deck" in critical[0].text.lower()
    (grouped,) = [entry for entry in commitments if entry.text.startswith("Also overdue:")]
    assert grouped.severity == Severity.warning
    assert "Send rollout plan" in grouped.text
    (customer,) = [entry for entry in commitments if "pipeline shortlist" in entry.text.lower()]
    assert customer.severity == Severity.info


async def test_overdue_alert_restatement_is_removed(world: World) -> None:
    def draft(prompt: str) -> BriefDraft:
        deck_id = evidence_ids(prompt, "pricing deck")
        return BriefDraft(
            sections={
                SectionKey.alerts: [item("Pricing deck overdue", deck_id)],
            }
        )

    brief, _ = await make(world, draft)

    assert section(brief, SectionKey.alerts) == []


async def test_unresolved_objection_cited_via_reflect_source(world: World) -> None:
    brief, llm = await make(world)

    (obj,) = section(brief, SectionKey.unresolved_objections)
    assert [c.meeting_id for c in obj.citations] == ["m3_finedge"]
    assert obj.citations[0].meeting_date == date(2026, 8, 12)
    # Only the unresolved objection is evidence.
    assert "SOC 2" in llm.calls[0].prompt
    assert "Pipeline limit" not in llm.calls[0].prompt


async def test_where_left_off_cites_latest_done_meeting(world: World) -> None:
    brief, _ = await make(world)

    (wlo,) = section(brief, SectionKey.where_left_off)
    (c,) = wlo.citations
    assert c.source_type == SourceType.mental_model
    assert (c.meeting_id, c.meeting_date) == ("m5_finedge", date(2026, 9, 15))
    assert c.quote and c.quote.startswith("Evaluation stage")


# ---- citation invariants --------------------------------------------------------------


async def test_every_memory_item_has_a_full_citation(world: World) -> None:
    brief, _ = await make(world)

    assert brief.mode == "memory"
    items = all_items(brief)
    assert items
    for it in items:
        assert it.citations, it.text
        for c in it.citations:
            assert c.meeting_id and c.meeting_date and c.quote and c.label
            assert len(c.quote) <= 200
    assert brief.facts_used > 0


async def test_unresolved_evidence_ids_are_dropped(world: World) -> None:
    def draft(prompt: str) -> BriefDraft:
        return BriefDraft(
            sections={
                SectionKey.watch_outs: [
                    item("kept", [*evidence_ids(prompt, "DataHawk"), "mem:99", "nonsense"]),
                    item("only bogus", ["mem:99", "led:42"]),
                ]
            }
        )

    brief, _ = await make(world, draft)

    (competitor,) = section(brief, SectionKey.watch_outs)
    assert competitor.text == "FinEdge has looked at DataHawk."
    assert len(competitor.citations) == 1


async def test_llm_item_without_evidence_is_dropped(world: World) -> None:
    def draft(prompt: str) -> BriefDraft:
        return BriefDraft(
            sections={
                SectionKey.agenda: [item("Invented talking point", [])],
                SectionKey.watch_outs: [item("DataHawk", evidence_ids(prompt, "DataHawk"))],
            }
        )

    brief, _ = await make(world, draft)

    assert section(brief, SectionKey.agenda) == []
    assert all(i.text != "Invented talking point" for i in all_items(brief))


async def test_llm_written_attendees_section_is_ignored(world: World) -> None:
    def draft(prompt: str) -> BriefDraft:
        return BriefDraft(
            sections={
                SectionKey.attendees: [item("Made up person", evidence_ids(prompt, "DataHawk"))]
            }
        )

    brief, _ = await make(world, draft)

    assert all(i.text != "Made up person" for i in all_items(brief))


# ---- attendees built in code ------------------------------------------------------------


async def test_attendees_section_built_in_code_with_citations(world: World) -> None:
    brief, _ = await make(world)

    by_contact = {i.contact_ids[0]: i for i in section(brief, SectionKey.attendees)}
    # Ours (c_priya) is not listed; Vikram was never met and Karan has no spoken
    # line in his latest prior meeting, so both are dropped.
    assert set(by_contact) == {"c_rahul", "c_anita"}
    rahul = by_contact["c_rahul"]
    assert rahul.text == "Rahul Mehta, VP Engineering"
    (c,) = rahul.citations
    assert (c.meeting_id, c.meeting_date) == ("m4_finedge", date(2026, 8, 27))
    assert c.quote == RAHUL_M4_LINE
    assert c.label == "Pilot scoping on Aug 27, 2026"
    anita_c = by_contact["c_anita"].citations[0]
    assert (anita_c.meeting_id, anita_c.quote) == ("m2_finedge", ANITA_M2_LINE)
    for it in by_contact.values():
        assert all("attended" not in (c.quote or "") for c in it.citations)


async def test_overdue_item_with_empty_source_quote_falls_back_to_commitment_text(
    world: World,
) -> None:
    with Session(world.engine) as s:
        deck = s.get(Commitment, "cm_deck")
        assert deck is not None
        deck.source_quote = ""
        s.add(deck)
        s.commit()

    brief, _ = await make(world, lambda p: BriefDraft(sections={}))

    (forced,) = section(brief, SectionKey.open_commitments)
    (c,) = forced.citations
    assert c.quote == "Send revised pricing deck with pilot option"
    assert c.meeting_id == "m4_finedge" and c.meeting_date == date(2026, 8, 27)


# ---- no_memory ----------------------------------------------------------------------------


class SpyMemory(MemoryService):
    """Delegates to a FakeMemoryService but records every method called."""

    def __init__(self, inner: MemoryService, fail: set[str] | None = None) -> None:
        self.inner = inner
        self.calls: list[str] = []
        self.fail = fail or set()

    def _note(self, name: str) -> None:
        self.calls.append(name)
        if name in self.fail:
            raise MemoryUnavailableError(f"{name} unavailable")

    async def aclose(self) -> None:
        self._note("aclose")

    async def ensure_bank(self) -> None:
        self._note("ensure_bank")

    async def ensure_mental_models(self, accounts: Sequence[tuple[str, str]]) -> None:
        self._note("ensure_mental_models")

    async def retain_meeting(self, **kwargs: Any) -> None:
        self._note("retain_meeting")

    async def retain_note(self, **kwargs: Any) -> None:
        self._note("retain_note")

    async def retain_preference(self, sentence: str) -> None:
        self._note("retain_preference")

    async def recall_facts(
        self, *, query: str, tags: Sequence[str], fact_kind: FactKind | None = None
    ) -> list[MemoryHit]:
        self._note("recall_facts")
        return await self.inner.recall_facts(query=query, tags=tags, fact_kind=fact_kind)

    async def reflect_structured(
        self, *, query: str, tags: Sequence[str], schema: type[BaseModel], budget: str = "mid"
    ) -> ReflectResult:
        self._note("reflect_structured")
        return await self.inner.reflect_structured(
            query=query, tags=tags, schema=schema, budget=budget
        )

    async def get_mental_model(self, name: str) -> MentalModelText | None:
        self._note("get_mental_model")
        return await self.inner.get_mental_model(name)

    async def timeline(self, contact_id: str) -> list[MemoryHit]:
        self._note("timeline")
        return await self.inner.timeline(contact_id)

    async def resolve_sources(self, hits: Sequence[MemoryHit]) -> list[MemoryHit]:
        self._note("resolve_sources")
        return await self.inner.resolve_sources(hits)

    async def wait_until_idle(self, timeout_s: float = 60.0) -> bool:
        self._note("wait_until_idle")
        return True

    async def delete_bank(self, bank_id: str) -> None:
        self._note("delete_bank")


async def test_no_memory_zero_citations_and_zero_memory_or_ledger_calls(
    world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = SpyMemory(world.memory)

    def boom(*args: Any, **kwargs: Any) -> list[Commitment]:
        raise AssertionError("no_memory must not read the ledger")

    monkeypatch.setattr(repository, "list_commitments_for_account", boom)
    monkeypatch.setattr(repository, "list_overdue_commitments", boom)

    def generic(prompt: str) -> BriefDraft:
        # A model given no evidence writes only generic items with no evidence ids.
        return BriefDraft(
            sections={
                SectionKey.agenda: [item("Review goals for the pilot decision", [])],
                SectionKey.open_commitments: [item("Nothing known yet", ["led:1", "mem:1"])],
            }
        )

    brief, llm = await make(world, generic, mode="no_memory", memory=spy)

    assert spy.calls == []
    assert world.memory.get_memory_calls == []
    assert world.memory.reflect_calls == []
    assert brief.mode == "no_memory"
    assert brief.facts_used == 0
    items = all_items(brief)
    assert items
    assert all(i.citations == [] for i in items)
    # Attendees: names and roles only, no citations.
    attendees = section(brief, SectionKey.attendees)
    assert {i.text for i in attendees} == {
        "Rahul Mehta, VP Engineering",
        "Anita Desai, CFO",
        "Karan Shah, Data Platform Lead",
        "Vikram Rao, CTO",
    }
    # No fixture facts anywhere in what the model saw or what we return.
    blob = llm.calls[0].prompt + brief.model_dump_json()
    for beat in ("pricing deck", "Ananya", "DataHawk", "40K", "SOC 2"):
        assert beat not in blob
    assert "(none)" in llm.calls[0].prompt


async def test_no_memory_uses_the_same_prompt_as_memory(world: World) -> None:
    _, memory_llm = await make(world)
    _, plain_llm = await make(world, lambda p: BriefDraft(sections={}), mode="no_memory")

    memory_prompt, plain_prompt = memory_llm.calls[0].prompt, plain_llm.calls[0].prompt
    assert plain_llm.calls[0].schema is BriefDraft
    assert memory_llm.calls[0].temperature == plain_llm.calls[0].temperature == 0.3

    def strip_evidence(prompt: str) -> str:
        head, _, rest = prompt.partition("(the ONLY facts you may use; each has an id):\n")
        _, _, tail = rest.partition("\n\nUser's brief style:")
        return head + "<EVIDENCE>" + "\n\nUser's brief style:" + tail

    assert strip_evidence(memory_prompt) == strip_evidence(plain_prompt)
    assert memory_prompt != plain_prompt


# ---- degradation --------------------------------------------------------------------------


async def test_memory_failure_in_one_section_degrades_only_that_section(
    world: World,
) -> None:
    spy = SpyMemory(world.memory)
    spy.fail = set()

    # Objections reflect fails; everything else works.
    world.memory._reflect_queue.clear()
    world.memory.queue_reflect_error(MemoryUnavailableError("reflect down"))

    brief, _ = await make(world, memory=spy)

    assert section(brief, SectionKey.unresolved_objections) == []
    assert section(brief, SectionKey.personal_touchpoints)
    assert section(brief, SectionKey.watch_outs)
    assert section(brief, SectionKey.open_commitments)


async def test_recall_failure_degrades_only_recall_sections(world: World) -> None:
    spy = SpyMemory(world.memory, fail={"recall_facts"})

    brief, _ = await make(world, memory=spy)

    assert section(brief, SectionKey.personal_touchpoints) == []
    assert section(brief, SectionKey.watch_outs) == []
    assert section(brief, SectionKey.unresolved_objections)
    assert section(brief, SectionKey.open_commitments)


async def test_every_memory_call_failing_raises_memory_unavailable(
    world: World,
) -> None:
    spy = SpyMemory(world.memory, fail={"recall_facts", "reflect_structured", "get_mental_model"})
    llm = FakeLLM()

    with pytest.raises(MemoryUnavailableError):
        await generate_brief(
            M6, "memory", llm=llm, memory=spy, session_factory=world.session_factory
        )
    assert llm.calls == []


async def test_llm_timeout_fails_the_brief_and_persists_nothing(world: World) -> None:
    llm = FakeLLM()
    llm.queue_error(LLMTimeoutError("slow"))

    with pytest.raises(LLMTimeoutError):
        await generate_brief(
            M6, "memory", llm=llm, memory=world.memory, session_factory=world.session_factory
        )

    assert len(llm.calls) == 1  # no retries of ours
    with Session(world.engine) as s:
        assert s.exec(select(BriefRecord)).all() == []


def test_default_brief_llm_uses_the_120s_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_get(*args: Any, **kwargs: Any) -> str:
        seen.update(kwargs)
        return "client"

    monkeypatch.setattr(brief_module, "get_llm_client", fake_get)

    assert default_brief_llm() == "client"  # type: ignore[comparison-overlap]
    assert seen == {"timeout_seconds": 120}
    assert BRIEF_LLM_TIMEOUT_SECONDS == 120


# ---- persona -----------------------------------------------------------------------------


async def test_prompt_and_brief_never_contain_the_demo_user_id(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "demo_user_id", "user-demo-thomas")
    brief, llm = await make(world)
    _, plain_llm = await make(world, lambda p: BriefDraft(sections={}), mode="no_memory")

    blob = "\n".join([llm.calls[0].prompt, plain_llm.calls[0].prompt, brief.model_dump_json()])
    assert "user-demo-thomas" not in blob
    assert settings.demo_user_id not in blob
    assert "Priya Nair, an account executive at Tracewise" in llm.calls[0].prompt


def test_load_persona_reads_seeded_company_file() -> None:
    persona = load_persona()
    assert (persona.user_name, persona.our_company) == ("Priya Nair", "Tracewise")


def test_load_persona_missing_file_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    load_persona.cache_clear()
    monkeypatch.setattr(brief_module, "_COMPANY_JSON", tmp_path / "nope.json")
    try:
        with pytest.raises(FileNotFoundError, match="company.json"):
            load_persona()
    finally:
        load_persona.cache_clear()


def test_render_brief_prompt_lists_attendees_with_ids(world: World) -> None:
    from app.db.brief_repo import load_brief_inputs

    inputs = load_brief_inputs(world.session_factory, M6)
    prompt = render_brief_prompt(persona=load_persona(), inputs=inputs, evidence_text="(none)")

    assert "c_rahul: Rahul Mehta (VP Engineering)" in prompt
    assert "attendees" not in prompt.split("sections:")[1].split("\n")[0]
    assert "Today is 2026-09-28" in prompt


async def test_r3_builds_cited_b5_alert_from_attendance_and_recorded_output(
    world: World,
) -> None:
    from app.memory.tags import account_tag, meeting_tag

    world.memory.seed_fact(
        "o_security_gap_m5",
        "Karan said Anita Desai has not been in any of the security conversations.",
        tags=[account_tag("acc_finedge"), meeting_tag("m5_finedge")],
        memory_type="observation",
        mentioned_at=date(2026, 9, 15),
    )
    with Session(world.engine) as session:
        m3 = session.get(Meeting, "m3_finedge")
        m5 = session.get(Meeting, "m5_finedge")
        assert m3 is not None and m5 is not None
        m3.transcript = (
            "[2026-08-12T10:06:30+05:30] Sneha Iyer (IT Security Manager, FinEdge): "
            "I need SOC 2 Type II and confirmation of India data residency."
        )
        m5.transcript = (
            "[2026-09-15T10:05:45+05:30] Karan Shah (Data Platform Lead, FinEdge): "
            "Anita hasn't been in any of the security conversations."
        )
        session.add_all([m3, m5])
        session.commit()
    world.memory.queue_reflect_response(
        ReflectResult(
            text="security gap",
            structured={
                "gaps": [{
                    "concern": "SOC 2 and India data-residency",
                    "raised_by": "Sneha Iyer",
                    "answered_on": "2026-09-29",
                    "not_heard_by": ["Anita Desai"],
                    "extra": "tolerated",
                }]
            },
            sources=[
                MemoryHit(
                    memory_id="o_sec",
                    text="Sneha raised a concern about the SOC 2 report and data residency",
                    meeting_id=None,
                    meeting_date=None,
                    tags=[],
                ),
                MemoryHit(
                    memory_id="o_security_gap_m5",
                    text=(
                        "Karan said Anita Desai has not been in any of the security conversations."
                    ),
                    meeting_id=None,
                    meeting_date=None,
                    tags=[],
                ),
            ],
            structured_error=None,
        )
    )

    brief, _ = await make(world)

    assert len(world.memory.reflect_calls) == 2
    assert set(world.memory.get_memory_calls) >= {"o_sec", "o_security_gap_m5"}
    alerts = section(brief, SectionKey.alerts)
    assert alerts, (world.memory.reflect_calls, world.memory.get_memory_calls)
    alert = next(i for i in alerts if "SOC 2 and India" in i.text)
    assert alert.severity == Severity.warning
    assert alert.contact_ids == ["c_anita"]
    assert {citation.meeting_id for citation in alert.citations} == {"m3_finedge", "m5_finedge"}
    assert any("Anita hasn't been" in citation.quote for citation in alert.citations)
    r3_query, r3_tags, _ = next(
        call for call in world.memory.reflect_calls if "attendees from" in call[0]
    )
    assert "Anita Desai" in r3_query and "Rahul Mehta" in r3_query
    assert r3_tags == [account_tag("acc_finedge")]


# ---- cache ------------------------------------------------------------------------------


async def test_cache_returns_stored_brief_and_upserts_per_meeting_and_mode(
    world: World,
) -> None:
    assert await get_cached_brief(M6, "memory", session_factory=world.session_factory) is None

    first, _ = await make(world)
    cached = await get_cached_brief(M6, "memory", session_factory=world.session_factory)
    assert cached == first
    assert await get_cached_brief(M6, "no_memory", session_factory=world.session_factory) is None

    queue_objections(world.memory)
    second, _ = await make(world)  # explicit refresh
    assert second.id == first.id  # same record, so Feedback keeps pointing at it
    with Session(world.engine) as s:
        assert len(s.exec(select(BriefRecord)).all()) == 1

    await make(world, lambda p: BriefDraft(sections={}), mode="no_memory")
    with Session(world.engine) as s:
        assert {r.mode for r in s.exec(select(BriefRecord)).all()} == {"memory", "no_memory"}


@pytest.mark.parametrize(("delta_hours", "expect_cached"), [(1, False), (-1, True)])
async def test_cache_invalidated_by_later_ingest_on_the_account(
    world: World,
    delta_hours: int,
    expect_cached: bool,
) -> None:
    brief, _ = await make(world)
    ingested_at = datetime.now(UTC) + timedelta(hours=delta_hours)
    with Session(world.engine) as s:
        meeting = s.get(Meeting, "m5_finedge")
        assert meeting is not None
        meeting.ingested_at = ingested_at
        s.add(meeting)
        s.commit()

    cached = await get_cached_brief(M6, "memory", session_factory=world.session_factory)

    assert (cached == brief) if expect_cached else (cached is None)


# ---- helpers ---------------------------------------------------------------------------


def test_first_line_spoken_by_parses_speaker_lines() -> None:
    transcript = (
        "[2026-08-27T10:00:08+05:30] Priya Nair (Account Executive, Tracewise): Hi all.\n"
        "not a transcript line\n"
        "[2026-08-27T10:00:15+05:30] Rahul Mehta (VP Engineering, FinEdge Payments): Yep, here.\n"
        "[2026-08-27T10:00:20+05:30] Rahul Mehta (VP Engineering, FinEdge Payments): Later line."
    )
    assert first_line_spoken_by(transcript, ["Rahul Mehta"]) == "Yep, here."
    assert first_line_spoken_by(transcript, ["rahul mehta"]) == "Yep, here."
    assert first_line_spoken_by(transcript, ["Karan Shah", "KS"]) is None
    assert first_line_spoken_by(None, ["Rahul Mehta"]) is None
