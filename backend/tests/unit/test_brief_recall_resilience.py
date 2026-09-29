"""Brief recall resilience: 25 s brief timeout, concurrency cap, dedupe, loud timeouts,
no persistence of degraded briefs, and a robust deal snapshot. Fakes only, no network."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator, Sequence
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlmodel import Session, select

from app.core.errors import MemoryUnavailableError
from app.db.models import Account, BriefRecord
from app.memory import memory_service as ms
from app.memory.memory_service import HindsightMemoryService
from app.memory.tags import account_tag, contact_tag, fact_kind_tag, meeting_tag
from app.schemas.brief import BriefDraft, SectionKey
from app.schemas.enums import FactKind
from app.schemas.memory import MemoryHit
from app.services.brief import (
    BRIEF_RECALL_TIMEOUT_S,
    MAX_CONCURRENT_RECALLS,
    BriefRecalls,
    Timings,
    _cross_deal_recall,
    _deal_snapshot_parts,
    load_persona,
)
from tests.fakes.fake_memory_service import FakeMemoryService
from tests.unit.brief_world import ACC, M6, World, make_world
from tests.unit.test_brief_service import make, section


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    yield from make_world(tmp_path)


class TrackingMemory(FakeMemoryService):
    """Fake that records how many recalls are in flight at once."""

    def __init__(self) -> None:
        super().__init__()
        self.in_flight = 0
        self.max_in_flight = 0

    async def recall_facts(
        self,
        *,
        query: str,
        tags: Sequence[str],
        fact_kind: FactKind | None = None,
        timeout_s: float | None = None,
    ) -> list[MemoryHit]:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0.01)
            return await super().recall_facts(
                query=query, tags=tags, fact_kind=fact_kind, timeout_s=timeout_s
            )
        finally:
            self.in_flight -= 1


def persisted(world: World) -> list[BriefRecord]:
    with Session(world.engine) as s:
        return list(s.exec(select(BriefRecord).where(BriefRecord.meeting_id == M6)).all())


def hit(
    memory_id: str, text: str, meeting_id: str, when: date, kind: FactKind | None = None
) -> MemoryHit:
    tags = [account_tag(ACC), meeting_tag(meeting_id)]
    if kind:
        tags.append(fact_kind_tag(kind))
    return MemoryHit(
        memory_id=memory_id, text=text, meeting_id=meeting_id, meeting_date=when, tags=tags
    )


# ---- a. timeouts -----------------------------------------------------------------------


def test_brief_recall_timeout_is_25s_and_default_stays_5s() -> None:
    assert BRIEF_RECALL_TIMEOUT_S == 25.0
    assert ms.RECALL_TIMEOUT_S == 5.0


async def test_every_brief_recall_passes_the_25s_timeout(world: World) -> None:
    await make(world)
    assert world.memory.recall_timeouts
    assert set(world.memory.recall_timeouts) == {25.0}


class _SlowRecallClient:
    def __init__(self, delay: float) -> None:
        self.delay = delay

    async def arecall(self, **kwargs: Any) -> Any:
        await asyncio.sleep(self.delay)
        return SimpleNamespace(results=[])


async def test_hindsight_recall_uses_override_else_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ms, "RECALL_TIMEOUT_S", 0.02)
    service = HindsightMemoryService(client=_SlowRecallClient(0.1))  # type: ignore[arg-type]
    with pytest.raises(MemoryUnavailableError, match=r"after 0\.02s"):
        await service.recall_facts(query="q", tags=["a"])
    assert await service.recall_facts(query="q", tags=["a"], timeout_s=2.0) == []


async def test_timeline_keeps_the_default_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ms, "RECALL_TIMEOUT_S", 0.02)
    service = HindsightMemoryService(client=_SlowRecallClient(0.1))  # type: ignore[arg-type]
    with pytest.raises(MemoryUnavailableError, match=r"Timeline recall timed out after 0\.02s"):
        await service.timeline("c_x")


# ---- b. concurrency cap + dedupe ------------------------------------------------------


async def test_full_brief_never_has_more_than_4_recalls_in_flight(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(world.engine) as s:
        for i in range(3):
            s.add(Account(id=f"acc_o{i}", name=f"Other {i}", industry="SaaS", stage="evaluation"))
        s.commit()
    original = world.memory.recall_facts
    state = {"now": 0, "max": 0}

    async def tracked(**kwargs: Any) -> list[MemoryHit]:
        state["now"] += 1
        state["max"] = max(state["max"], state["now"])
        try:
            await asyncio.sleep(0.01)
            return await original(**kwargs)
        finally:
            state["now"] -= 1

    monkeypatch.setattr(world.memory, "recall_facts", tracked)
    await make(world)
    assert 1 < state["max"] <= MAX_CONCURRENT_RECALLS == 4


async def test_cross_deal_stage_shares_the_cap_with_other_recalls() -> None:
    memory = TrackingMemory()
    recalls = BriefRecalls(memory)
    others = [SimpleNamespace(id=f"acc_o{i}") for i in range(5)]
    topics = [
        hit(f"t{i}", f"objection number {i}", "m3_finedge", date(2026, 8, 12)) for i in range(3)
    ]
    extra = [
        recalls.facts(query=f"extra {i}", tags=[account_tag(ACC)], stage="x") for i in range(6)
    ]
    await asyncio.gather(
        *extra,
        _cross_deal_recall(
            memory,
            current_account_id=ACC,
            other_accounts=others,
            objections=topics,
            timings=Timings(),
            recalls=recalls,
        ),
    )
    assert len(memory.recall_calls) == 6 + 15
    assert memory.max_in_flight == 4


async def test_identical_recalls_call_memory_once_and_share_the_result() -> None:
    memory = TrackingMemory()
    memory.seed_fact(
        "f1",
        "budget about $40K",
        tags=[account_tag(ACC)],
        meeting_id="m2_finedge",
        meeting_date=date(2026, 7, 28),
    )
    recalls = BriefRecalls(memory)
    args: dict[str, Any] = {"query": "budget", "tags": [account_tag(ACC)]}
    results = await asyncio.gather(
        recalls.facts(**args, stage="a"),
        recalls.facts(**args, stage="b"),
        recalls.facts(**args, fact_kind=FactKind.deal_fact, stage="c"),  # different key
        recalls.facts(**args, stage="d"),
    )
    assert len(memory.recall_calls) == 2
    assert [h.memory_id for h in results[0]] == [h.memory_id for h in results[3]] == ["f1"]


async def test_cross_deal_dedupes_repeated_topic_text() -> None:
    memory = FakeMemoryService()
    same = [hit(f"t{i}", "SOC 2 needed", "m3_finedge", date(2026, 8, 12)) for i in range(3)]
    await _cross_deal_recall(
        memory,
        current_account_id=ACC,
        other_accounts=[SimpleNamespace(id="acc_o1"), SimpleNamespace(id="acc_o2")],
        objections=same,
        timings=Timings(),
    )
    assert len(memory.recall_calls) == 2


async def test_full_brief_makes_no_duplicate_recall(world: World) -> None:
    await make(world)
    keys = [(q, tuple(t), k) for q, t, k in world.memory.recall_calls]
    assert len(keys) == len(set(keys))


# ---- c. loud timeouts, degraded briefs are not persisted --------------------------------


def fail_recalls(world: World, monkeypatch: pytest.MonkeyPatch, predicate: Any) -> None:
    original = world.memory.recall_facts

    async def flaky(
        *,
        query: str,
        tags: Sequence[str],
        fact_kind: FactKind | None = None,
        timeout_s: float | None = None,
    ) -> list[MemoryHit]:
        if predicate(query, tuple(tags), fact_kind):
            raise MemoryUnavailableError("Recall timed out after 25s.")
        return await original(query=query, tags=tags, fact_kind=fact_kind, timeout_s=timeout_s)

    monkeypatch.setattr(world.memory, "recall_facts", flaky)


@pytest.mark.parametrize(
    ("stage", "predicate"),
    [
        ("watch_outs", lambda q, t, k: k == FactKind.competitor),
        ("budget_snapshot", lambda q, t, k: q.startswith("account budget")),
        ("decision_snapshot", lambda q, t, k: q.startswith("decision date")),
        ("security_absence", lambda q, t, k: "hasn't been in the security" in q),
        ("security_gaps", lambda q, t, k: q == " ".join(load_persona().security_keywords)),
        ("personal_touchpoints:c_rahul", lambda q, t, k: t == (contact_tag("c_rahul"),)),
    ],
)
async def test_beat_critical_timeout_returns_but_does_not_persist(
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    stage: str,
    predicate: Any,
) -> None:
    fail_recalls(world, monkeypatch, predicate)
    with caplog.at_level(logging.WARNING):
        brief, _ = await make(world)
    assert brief.sections  # still returned to the POST caller
    assert persisted(world) == []
    text = caplog.text
    assert f"brief.recall_timeout stage={stage}" in text
    assert "elapsed_ms=" in text
    assert "brief.degraded_not_persisted" in text


async def test_cross_deal_timeout_is_beat_critical(
    world: World, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with Session(world.engine) as s:
        s.add(Account(id="acc_o1", name="Other", industry="SaaS", stage="evaluation"))
        s.commit()
    fail_recalls(world, monkeypatch, lambda q, t, k: t == (account_tag("acc_o1"),))
    with caplog.at_level(logging.WARNING):
        brief, _ = await make(world)
    assert brief.sections
    assert persisted(world) == []
    assert "brief.recall_timeout stage=cross_deal" in caplog.text


async def test_non_critical_failure_still_persists(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    fail_recalls(world, monkeypatch, lambda q, t, k: k == FactKind.objection)
    await make(world)
    assert len(persisted(world)) == 1


async def test_healthy_brief_is_persisted(world: World) -> None:
    await make(world)
    assert len(persisted(world)) == 1


# ---- d. deal snapshot -------------------------------------------------------------------

M2_BUDGET = "Anita: The budget is about $40K this fiscal year."
M5_ECHO = "Karan noted Anita's indicated about $40K this fiscal year, unclear if a hard ceiling."
DECISION = "Rahul said the pilot decision has to be made by Oct 31."
DATAHAWK = "DataHawk was mentioned as a cheaper competitor without India residency"


def snapshot(**overrides: Any) -> list[tuple[str, MemoryHit]]:
    args: dict[str, Any] = {
        "budget_hits": [
            hit("b5", M5_ECHO, "m5_finedge", date(2026, 9, 15), FactKind.deal_fact),
            hit("b2", M2_BUDGET, "m2_finedge", date(2026, 7, 28), FactKind.deal_fact),
        ],
        "decision_hits": [hit("d", DECISION, "m4_finedge", date(2026, 8, 27))],
        "competitor_hits": [hit("c", DATAHAWK, "m3_finedge", date(2026, 8, 12))],
        "competitors": ["DataHawk"],
        "deal_value_usd": 40000,
    }
    args.update(overrides)
    return _deal_snapshot_parts(**args)


def test_snapshot_has_budget_decision_and_competitor_cited_to_right_meetings() -> None:
    parts = snapshot()
    assert [(t, h.meeting_id) for t, h in parts] == [
        ("Budget about $40K", "m2_finedge"),  # originating statement, not the later echo
        ("Decision by Oct 31, 2026", "m4_finedge"),
        ("DataHawk evaluated", "m3_finedge"),
    ]


def test_budget_amount_comes_from_the_cited_hit_not_the_current_deal_value() -> None:
    parts = snapshot(deal_value_usd=75000)
    assert parts[0][0] == "Budget about $40K"
    assert parts[0][1].meeting_id == "m2_finedge"


def test_budget_survives_when_deal_value_is_missing() -> None:
    parts = snapshot(deal_value_usd=None)
    assert parts[0] == ("Budget about $40K", parts[0][1])


def test_decision_hit_with_a_date_beats_a_later_one_without() -> None:
    parts = snapshot(
        decision_hits=[
            hit("d2", "The decision is still pending.", "m5_finedge", date(2026, 9, 15)),
            hit("d", DECISION, "m4_finedge", date(2026, 8, 27)),
        ]
    )
    assert ("Decision by Oct 31, 2026", "m4_finedge") in [(t, h.meeting_id) for t, h in parts]


def test_no_budget_hit_never_invents_a_citation() -> None:
    parts = snapshot(budget_hits=[])
    assert not any(t.startswith("Budget") for t, _ in parts)


def test_budget_hit_without_dollar_figure_is_not_used() -> None:
    parts = snapshot(
        budget_hits=[hit("b", "Budget review scheduled", "m5_finedge", date(2026, 9, 15))]
    )
    assert not any(t.startswith("Budget") for t, _ in parts)


async def test_observation_budget_hit_without_metadata_is_resolved_for_the_snapshot(
    world: World,
) -> None:
    # Observation facts carry no meeting metadata; the snapshot must resolve them via tags.
    world.memory.seed_fact(
        "obs_budget",
        M2_BUDGET,
        tags=[account_tag(ACC), meeting_tag("m2_finedge"), fact_kind_tag(FactKind.deal_fact)],
        memory_type="observation",
        mentioned_at=date(2026, 7, 28),
    )
    world.memory.seed_fact(
        "w_decision",
        DECISION,
        tags=[account_tag(ACC), meeting_tag("m4_finedge"), fact_kind_tag(FactKind.deal_fact)],
        meeting_id="m4_finedge",
        meeting_date=date(2026, 8, 27),
    )
    brief, _ = await make(world, lambda p: BriefDraft(sections={SectionKey.where_left_off: []}))
    (snap,) = [i for i in section(brief, SectionKey.where_left_off) if "deal-snapshot" in i.id]
    assert "Budget about $40K" in snap.text
    assert "Decision by Oct 31, 2026" in snap.text
    assert "DataHawk evaluated" in snap.text
    assert {c.meeting_id for c in snap.citations} == {"m2_finedge", "m4_finedge", "m3_finedge"}


async def test_budget_recall_falls_back_when_the_fact_kind_label_is_missing(
    world: World,
) -> None:
    world.memory.seed_fact(
        "unlabelled",
        M2_BUDGET,
        tags=[account_tag(ACC), meeting_tag("m2_finedge")],
        meeting_id="m2_finedge",
        meeting_date=date(2026, 7, 28),
    )
    brief, _ = await make(world)
    (snap,) = [i for i in section(brief, SectionKey.where_left_off) if "deal-snapshot" in i.id]
    assert "Budget about $40K" in snap.text
