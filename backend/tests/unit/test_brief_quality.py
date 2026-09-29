"""T14b brief quality: recall fallbacks, top-3 per query, compact ledger evidence, recall-only
citations. FakeLLM/FakeMemoryService only, no network."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from datetime import date
from pathlib import Path

import pytest
from sqlmodel import Session, select

from app.core.errors import MemoryUnavailableError
from app.db.models import Commitment
from app.memory.tags import account_tag, contact_tag, fact_kind_tag, meeting_tag
from app.schemas.brief import BriefDraft, SectionKey, SourceType
from app.schemas.enums import CommitmentStatus, FactKind, Owner
from app.schemas.memory import MemoryHit
from app.services.brief import PERSONAL_QUERY, competitor_query, load_persona, top_distinct_hits
from tests.unit.brief_world import (
    ACC,
    DECK_QUOTE,
    World,
    evidence_ids,
    good_draft,
    item,
    make_world,
)
from tests.unit.test_brief_service import make, section

RecallCall = tuple[str, tuple[str, ...], FactKind | None]


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    yield from make_world(tmp_path)


def log_recalls(world: World, monkeypatch: pytest.MonkeyPatch) -> list[RecallCall]:
    calls: list[RecallCall] = []
    original = world.memory.recall_facts

    async def logged(
        *,
        query: str,
        tags: Sequence[str],
        fact_kind: FactKind | None = None,
        timeout_s: float | None = None,
    ) -> list[MemoryHit]:
        calls.append((query, tuple(tags), fact_kind))
        return await original(query=query, tags=tags, fact_kind=fact_kind)

    monkeypatch.setattr(world.memory, "recall_facts", logged)
    return calls


def hit(text: str, i: int = 0) -> MemoryHit:
    return MemoryHit(memory_id=f"h{i}", text=text, meeting_id="m1", meeting_date=None, tags=[])


# ---- top_distinct_hits ----------------------------------------------------------------


def test_top_distinct_hits_keeps_rank_order_dedupes_and_caps() -> None:
    hits = [
        hit("Rahul plays cricket every weekend", 1),
        hit("rahul PLAYS cricket, every weekend!", 2),  # same after normalisation
        hit("Rahul plays cricket every weekend with his team", 3),  # contains an earlier one
        hit("Rahul is travelling to Goa in December", 4),
        hit("Rahul runs marathons", 5),
        hit("Rahul has two dogs", 6),
    ]

    kept = top_distinct_hits(hits)

    assert [h.memory_id for h in kept] == ["h1", "h4", "h5"]
    assert top_distinct_hits([]) == []


def test_top_distinct_hits_drops_a_shorter_text_contained_in_a_kept_one() -> None:
    kept = top_distinct_hits([hit("Karan moved to Pune for work", 1), hit("moved to Pune", 2)])
    assert [h.memory_id for h in kept] == ["h1"]


# ---- watch-outs fallback ----------------------------------------------------------------


async def test_watch_outs_fallback_not_used_when_labelled_recall_has_hits(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = log_recalls(world, monkeypatch)

    await make(world)

    account_calls = [
        c for c in calls if c[1] == (account_tag(ACC),) and c[2] == FactKind.competitor
    ]
    assert account_calls == [
        (
            competitor_query(load_persona().competitors),
            (account_tag(ACC),),
            FactKind.competitor,
        )
    ]


async def test_watch_outs_fallback_used_when_labelled_recall_is_empty(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.memory.items = [i for i in world.memory.items if i.memory_id != "w_datahawk"]
    world.memory.seed_fact(
        "w_unlabelled",
        "Rahul said they are also comparing us against a cheaper vendor",
        tags=[account_tag(ACC), meeting_tag("m3_finedge")],
        meeting_id="m3_finedge",
        meeting_date=date(2026, 8, 12),
    )
    world.memory.items.insert(0, world.memory.items.pop())  # rank it first
    calls = log_recalls(world, monkeypatch)

    brief, llm = await make(
        world,
        lambda p: BriefDraft(
            sections={SectionKey.watch_outs: [item("Cheaper vendor", evidence_ids(p, "vendor"))]}
        ),
    )

    expected_query = competitor_query(load_persona().competitors)
    account_calls = [
        c for c in calls if c[1] == (account_tag(ACC),) and c[0] == expected_query
    ]
    assert [c[2] for c in account_calls] == [FactKind.competitor, None]
    assert all(c[0] == competitor_query(load_persona().competitors) for c in account_calls)
    (watch,) = section(brief, SectionKey.watch_outs)
    assert [c.meeting_id for c in watch.citations] == ["m3_finedge"]


# ---- personal touchpoints ------------------------------------------------------------------


async def test_personal_recall_one_targeted_query_per_external_attendee(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = log_recalls(world, monkeypatch)

    await make(world)

    external = {"c_rahul": "Rahul Mehta", "c_karan": "Karan Shah", "c_anita": "Anita Desai",
                "c_newbie": "Vikram Rao"}  # fmt: skip
    for contact_id, name in external.items():
        mine = [c for c in calls if c[1] == (contact_tag(contact_id),)]
        assert mine[0] == (
            f"{name} {PERSONAL_QUERY}",
            (contact_tag(contact_id),),
            FactKind.personal,
        )
        # Retry without fact_kind only when the labelled query found nothing.
        expected_extra = 0 if contact_id in {"c_rahul", "c_karan"} else 1
        assert len(mine) == 1 + expected_extra
        assert all(c[2] is None for c in mine[1:])
    assert not [c for c in calls if c[1] == (contact_tag("c_priya"),)]  # ours: no query


async def test_personal_hits_capped_at_three_deduped_and_in_rank_order(world: World) -> None:
    tags = [account_tag(ACC), contact_tag("c_rahul"), fact_kind_tag(FactKind.personal)]
    extras = [
        ("x1", "Rahul plays cricket every weekend", "m3_finedge"),
        ("x2", "rahul plays cricket every weekend!", "m3_finedge"),
        ("x3", "Rahul plays cricket every weekend with his team", "m3_finedge"),
        ("x4", "Rahul is travelling to Goa in December", "m4_finedge"),
        ("x5", "Rahul runs marathons", "m4_finedge"),
    ]
    for memory_id, text, meeting in extras:
        world.memory.seed_fact(
            memory_id,
            text,
            tags=[*tags, meeting_tag(meeting)],
            meeting_id=meeting,
            meeting_date=date(2026, 8, 12 if meeting == "m3_finedge" else 27),
        )

    _, llm = await make(world, lambda p: BriefDraft(sections={}))

    prompt = llm.calls[0].prompt
    lines = [
        ln
        for ln in prompt.splitlines()
        if ln.startswith("[mem:") and "Rahul" in ln and "Karan" not in ln
    ]
    # Rank order (w_ananya seeded first), NOT newest-first; x2/x3 are near-duplicates of x1.
    assert [("Ananya" in ln, "cricket" in ln, "Goa" in ln) for ln in lines] == [
        (True, False, False),
        (False, True, False),
        (False, False, True),
    ]
    assert "marathons" not in prompt


# ---- recall-only citations ------------------------------------------------------------------


async def test_recall_only_evidence_cites_recall_meetings_incl_resolved_observation(
    world: World,
) -> None:
    world.memory.mental_models.clear()
    with Session(world.engine) as s:
        for c in s.exec(select(Commitment)).all():
            s.delete(c)
        s.commit()
    # A recall hit that arrives WITHOUT meeting info (observation, multi-tag): must go through
    # resolve_sources. Its own tags carry no meeting; its source memory does.
    world.memory.seed_fact(
        "o_multi",
        "Karan mentioned Ananya's move to Pune again",
        tags=[account_tag(ACC), contact_tag("c_karan"), fact_kind_tag(FactKind.personal),
              meeting_tag("m3_finedge"), meeting_tag("m5_finedge")],
        memory_type="observation",
        source_memory_ids=["w_src"],
    )  # fmt: skip
    world.memory.seed_fact(
        "w_src",
        "Karan mentioned Ananya's move to Pune",
        tags=[account_tag(ACC), meeting_tag("m5_finedge")],
        meeting_id="m5_finedge",
        meeting_date=date(2026, 9, 15),
    )

    def draft(prompt: str) -> BriefDraft:
        return BriefDraft(
            sections={
                SectionKey.personal_touchpoints: [
                    item("Ask about Ananya's move", evidence_ids(prompt, "Ananya"))
                ],
                SectionKey.watch_outs: [item("Cheaper rival", evidence_ids(prompt, "DataHawk"))],
            }
        )

    brief, llm = await make(world, draft)

    assert "[mm:" not in llm.calls[0].prompt and "[led:" not in llm.calls[0].prompt
    (touch,) = section(brief, SectionKey.personal_touchpoints)
    (watch,) = section(brief, SectionKey.watch_outs)
    assert {c.source_type for c in touch.citations + watch.citations} == {SourceType.meeting}
    by_memory = {c.memory_id: c for c in touch.citations}
    assert by_memory["o_multi"].meeting_id == "m5_finedge"  # resolved via its source memory
    assert by_memory["o_multi"].meeting_date == date(2026, 9, 15)
    assert by_memory["o_multi"].quote == "Karan mentioned Ananya's move to Pune again"
    assert {c.meeting_id for c in touch.citations} >= {"m1_finedge", "m5_finedge"}
    assert [c.meeting_id for c in watch.citations] == ["m3_finedge"]
    assert watch.citations[0].quote and "DataHawk" in watch.citations[0].quote


# ---- ledger compaction ----------------------------------------------------------------------


async def test_b1_still_critical_with_85_open_rows_and_prompt_stays_small(world: World) -> None:
    with Session(world.engine) as s:
        for i in range(79):
            s.add(
                Commitment(
                    id=f"cm_undated{i}", account_id=ACC, meeting_id="m3_finedge", owner=Owner.us,
                    text=f"Follow up on undated item number {i}", due_date=None,
                    status=CommitmentStatus.open, source_quote=f"undated quote {i}",
                )
            )  # fmt: skip
        for i in range(5):  # 6 dated rows in total with cm_deck
            s.add(
                Commitment(
                    id=f"cm_dated{i}", account_id=ACC, meeting_id="m3_finedge", owner=Owner.them,
                    text=f"Dated item {i}", due_date=date(2026, 10, 1 + i),
                    status=CommitmentStatus.open, source_quote=f"dated quote {i}",
                )
            )  # fmt: skip
        s.commit()

    def omit_deck(prompt: str) -> BriefDraft:
        return BriefDraft(sections={})

    brief, llm = await make(world, omit_deck)

    prompt = llm.calls[0].prompt
    assert "undated" not in prompt
    assert prompt.count("[led:") == 6
    evidence_block = prompt.split("each has an id):\n")[1].split("\n\nUser's brief style:")[0]
    assert len(evidence_block.splitlines()) <= 25
    assert len(evidence_block) < 4000
    (forced,) = section(brief, SectionKey.open_commitments)  # appended, cited, critical
    assert forced.severity.value == "critical"
    assert forced.citations[0].quote == DECK_QUOTE


async def test_total_evidence_never_exceeds_the_cap(world: World) -> None:
    for i in range(30):
        world.memory.seed_fact(
            f"w_more{i}",
            f"Rahul shared personal detail number {i}",
            tags=[account_tag(ACC), contact_tag("c_rahul"), fact_kind_tag(FactKind.personal),
                  meeting_tag("m1_finedge")],
            meeting_id="m1_finedge",
            meeting_date=date(2026, 7, 14),
        )  # fmt: skip

    _, llm = await make(world, good_draft)

    ids = [ln for ln in llm.calls[0].prompt.splitlines() if ln.startswith("[")]
    assert 0 < len(ids) <= 25


# ---- logging ---------------------------------------------------------------------------------


async def test_recall_and_evidence_counts_logged_at_debug_without_content(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        await make(world)

    recall_lines = [r for r in caplog.records if r.getMessage().startswith("brief.recall ")]
    evidence_lines = [r for r in caplog.records if r.getMessage().startswith("brief.evidence ")]
    assert recall_lines and evidence_lines
    assert all(r.levelno == logging.DEBUG for r in recall_lines + evidence_lines)
    assert all("Ananya" not in r.getMessage() for r in caplog.records)


# ---- recall floor and overdue cap -----------------------------------------------------------


async def test_many_overdue_rows_do_not_squeeze_out_recall_and_all_overdue_stay_in_brief(
    world: World,
) -> None:
    with Session(world.engine) as s:
        for i in range(13):  # 14 dated overdue rows with cm_deck
            s.add(
                Commitment(
                    id=f"cm_over{i:02d}", account_id=ACC, meeting_id="m3_finedge", owner=Owner.us,
                    text=f"Overdue promise {i}", due_date=date(2026, 9, 4 + i),
                    status=CommitmentStatus.open, source_quote=f"overdue quote {i}",
                )
            )  # fmt: skip
        s.commit()

    def only_recall(prompt: str) -> BriefDraft:
        return BriefDraft(
            sections={
                SectionKey.personal_touchpoints: [
                    item("Ask about Ananya", evidence_ids(prompt, "Ananya"))
                ],
                SectionKey.watch_outs: [item("Cheaper rival", evidence_ids(prompt, "DataHawk"))],
            }
        )

    brief, llm = await make(world, only_recall)

    prompt = llm.calls[0].prompt
    assert prompt.count("[led:") == 8  # MAX_OVERDUE_EVIDENCE
    assert "Ananya" in prompt and "DataHawk" in prompt  # B3 / B4 evidence survived
    assert len([ln for ln in prompt.splitlines() if ln.startswith("[")]) <= 25
    assert section(brief, SectionKey.personal_touchpoints)
    assert section(brief, SectionKey.watch_outs)
    forced = section(brief, SectionKey.open_commitments)
    assert len(forced) == 2  # the red item and grouped warning cover every overdue row
    for it in forced:
        assert it.citations[0].meeting_id and it.citations[0].quote
    # Only the most overdue us-owned row stays critical.
    assert [i.severity.value for i in forced].count("critical") == 1
    assert "pricing deck" in forced[0].text


async def test_top_five_resolved_keep_first_three_that_resolve(world: World) -> None:
    tags = [account_tag(ACC), contact_tag("c_rahul"), fact_kind_tag(FactKind.personal)]
    for memory_id, text in [("bad1", "Rahul unresolvable one"), ("bad2", "Rahul unresolvable two")]:
        world.memory.seed_fact(memory_id, text, tags=tags, memory_type="observation")
        world.memory.items.insert(0, world.memory.items.pop())  # rank first, no meeting anywhere
    for memory_id in ("g1", "g2", "g3"):
        world.memory.seed_fact(
            memory_id,
            f"Rahul good fact {memory_id}",
            tags=[*tags, meeting_tag("m3_finedge")],
            meeting_id="m3_finedge",
            meeting_date=date(2026, 8, 12),
        )

    _, llm = await make(world, lambda p: BriefDraft(sections={}))

    prompt = llm.calls[0].prompt
    assert "unresolvable" not in prompt  # unresolved top hits are skipped, not cited
    # Candidates by rank: bad1, bad2, w_ananya, g1, g2 (g3 is 6th). First three that resolve:
    assert "Rahul's daughter Ananya" in prompt
    assert "good fact g1" in prompt and "good fact g2" in prompt
    assert "good fact g3" not in prompt


# ---- one failing call degrades only its own section ------------------------------------------


def fail_recall_when(world: World, monkeypatch: pytest.MonkeyPatch, predicate: object) -> None:
    original = world.memory.recall_facts

    async def flaky(
        *,
        query: str,
        tags: Sequence[str],
        fact_kind: FactKind | None = None,
        timeout_s: float | None = None,
    ) -> list[MemoryHit]:
        if predicate(tuple(tags), fact_kind):  # type: ignore[operator]
            raise MemoryUnavailableError("recall down")
        return await original(query=query, tags=tags, fact_kind=fact_kind)

    monkeypatch.setattr(world.memory, "recall_facts", flaky)


async def test_labelled_watch_out_call_failing_degrades_only_watch_outs(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    fail_recall_when(world, monkeypatch, lambda tags, kind: kind == FactKind.competitor)

    brief, _ = await make(world)

    assert section(brief, SectionKey.watch_outs) == []
    assert section(brief, SectionKey.personal_touchpoints)
    assert section(brief, SectionKey.unresolved_objections)
    assert section(brief, SectionKey.open_commitments)


async def test_watch_out_fallback_call_failing_degrades_only_watch_outs(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.memory.items = [i for i in world.memory.items if i.memory_id != "w_datahawk"]
    fail_recall_when(
        world, monkeypatch, lambda tags, kind: tags == (account_tag(ACC),) and kind is None
    )

    brief, _ = await make(world)

    assert section(brief, SectionKey.watch_outs) == []
    assert section(brief, SectionKey.personal_touchpoints)
    assert section(brief, SectionKey.unresolved_objections)


async def test_one_attendees_recall_failing_degrades_only_that_attendee(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    fail_recall_when(world, monkeypatch, lambda tags, kind: tags == (contact_tag("c_rahul"),))

    brief, _ = await make(world)

    (touch,) = section(brief, SectionKey.personal_touchpoints)
    # Rahul's own M1 fact is gone; Karan's M5 observation (and everything else) still works.
    assert {c.meeting_id for c in touch.citations} == {"m5_finedge"}
    assert section(brief, SectionKey.watch_outs)
    assert section(brief, SectionKey.unresolved_objections)
