"""Evidence assembly: ids, order, cap, dropping unusable hits (services/evidence.py)."""

from __future__ import annotations

from datetime import date

from app.db.models import Commitment
from app.memory.memory_service import MentalModelText
from app.schemas.brief import SourceType
from app.schemas.enums import CommitmentStatus, Owner
from app.schemas.memory import MemoryHit
from app.services.evidence import (
    EVIDENCE_CAP,
    MeetingInfo,
    Objection,
    ObjectionReport,
    build_evidence,
    match_objection_sources,
    truncate,
)

TODAY = date(2026, 9, 28)
MEETINGS = {
    f"m{i}": MeetingInfo(id=f"m{i}", title=f"T{i}", date=date(2026, 7, i)) for i in range(1, 10)
}


def hit(i: int, meeting: str | None = "m1", text: str = "fact") -> MemoryHit:
    return MemoryHit(
        memory_id=f"h{i}", text=f"{text} {i}", meeting_id=meeting, meeting_date=None, tags=[]
    )


def commitment(cid: str, due: date | None, meeting: str = "m2") -> Commitment:
    return Commitment(
        id=cid,
        account_id="a",
        meeting_id=meeting,
        owner=Owner.us,
        text=f"do {cid}",
        due_date=due,
        status=CommitmentStatus.open,
        source_quote=f"quote {cid}",
    )


def test_ids_order_and_ledger_overdue_flag() -> None:
    table = build_evidence(
        mental_model=MentalModelText(
            id="relationship-a", name="n", content="Summary", last_refreshed_at=None
        ),
        latest_done_meeting=MEETINGS["m9"],
        recall_hits=[hit(1, "m1"), hit(2, "m3")],
        objections=[],
        commitments=[commitment("c1", date(2026, 9, 3)), commitment("c2", date(2026, 10, 1))],
        meetings=MEETINGS,
        today=TODAY,
    )

    assert [r.key for r in table.refs] == ["mm:1", "mem:1", "mem:2", "led:1", "led:2"]
    assert table.refs[0].source_type == SourceType.mental_model
    assert table.refs[0].meeting_id == "m9"
    assert [r.memory_id for r in table.refs[1:3]] == ["h1", "h2"]  # rank order kept, not recency
    led = {r.commitment_id: r for r in table.refs if r.source_type == SourceType.ledger}
    assert led["c1"].overdue and not led["c2"].overdue
    assert "OPEN, OVERDUE: us -> do c1, due 2026-09-03" in led["c1"].text
    assert table.get("[mem:1]") is table.refs[1]
    assert table.get("mem:77") is None


def test_mental_model_without_a_done_meeting_is_dropped() -> None:
    table = build_evidence(
        mental_model=MentalModelText(id="r", name="n", content="Summary", last_refreshed_at=None),
        latest_done_meeting=None,
        recall_hits=[],
        objections=[],
        commitments=[],
        meetings=MEETINGS,
        today=TODAY,
    )
    assert table.refs == []
    assert table.render() == "(none)"


def test_hits_without_meeting_are_unusable_and_duplicates_collapse() -> None:
    table = build_evidence(
        mental_model=None,
        latest_done_meeting=None,
        recall_hits=[hit(1, None), hit(2, "m1"), hit(2, "m1"), hit(3, "unknown")],
        objections=[],
        commitments=[],
        meetings=MEETINGS,
        today=TODAY,
    )

    assert [r.memory_id for r in table.refs] == ["h2"]  # h3's meeting has no date anywhere


def test_hit_date_falls_back_to_hit_when_meeting_unknown() -> None:
    dated = MemoryHit(
        memory_id="h9", text="t", meeting_id="mx", meeting_date=date(2026, 1, 2), tags=[]
    )
    table = build_evidence(
        mental_model=None,
        latest_done_meeting=None,
        recall_hits=[dated],
        objections=[],
        commitments=[],
        meetings=MEETINGS,
        today=TODAY,
    )
    assert table.refs[0].meeting_date == date(2026, 1, 2)


def test_cap_keeps_dated_ledger_and_truncates_recall_in_rank_order() -> None:
    hits = [hit(i, f"m{1 + i % 9}") for i in range(60)]
    table = build_evidence(
        mental_model=None,
        latest_done_meeting=None,
        recall_hits=hits,
        objections=[],
        commitments=[commitment("c1", date(2026, 9, 3)), commitment("c2", date(2026, 10, 1))],
        meetings=MEETINGS,
        today=TODAY,
    )

    assert len(table.refs) == EVIDENCE_CAP == 25
    assert [r.key for r in table.refs if r.key.startswith("led")] == ["led:1", "led:2"]
    ids = [r.memory_id for r in table.refs if r.key.startswith("mem")]
    assert ids == [f"h{i}" for i in range(23)]  # first N by rank


def test_ledger_never_sends_undated_rows_and_caps_upcoming_at_five() -> None:
    rows = [commitment(f"undated{i}", None) for i in range(79)]
    rows += [commitment("late1", date(2026, 9, 3)), commitment("late2", date(2026, 8, 20))]
    rows += [commitment(f"soon{i}", date(2026, 10, 1 + i)) for i in range(8)]
    rows += [commitment("today", TODAY)]
    table = build_evidence(
        mental_model=None,
        latest_done_meeting=None,
        recall_hits=[],
        objections=[],
        commitments=rows,
        meetings=MEETINGS,
        today=TODAY,
    )

    ids = [r.commitment_id for r in table.refs]
    assert not any(i and i.startswith("undated") for i in ids)
    assert ids[:2] == ["late2", "late1"]  # overdue first, oldest due date first
    assert ids[2:] == ["today", "soon0", "soon1", "soon2", "soon3"]  # 5 upcoming, soonest first
    assert [r.overdue for r in table.refs] == [True, True] + [False] * 5
    # Far smaller than sending all 91 open rows.
    assert len(table.render()) < 2000


def test_quote_and_prompt_text_are_bounded() -> None:
    long = "word " * 200
    table = build_evidence(
        mental_model=None,
        latest_done_meeting=None,
        recall_hits=[hit(1, "m1", long)],
        objections=[],
        commitments=[],
        meetings=MEETINGS,
        today=TODAY,
    )
    (ref,) = table.refs
    assert ref.quote is not None and len(ref.quote) <= 200
    assert len(ref.text) < 400
    assert truncate("short", 200) == "short"


def test_objection_matching_uses_unresolved_only_and_best_source() -> None:
    report = ObjectionReport(
        objections=[
            Objection(
                concern="SOC 2 report and data residency",
                raised_by="Sneha",
                raised_on=date(2026, 8, 12),
                resolved=False,
            ),
            Objection(
                concern="Pricing tiers",
                raised_by="Anita",
                raised_on=date(2026, 7, 28),
                resolved=True,
                resolution="Growth",
            ),
            Objection(
                concern="Completely unrelated gripe",
                raised_by="Zed",
                raised_on=date(2026, 1, 1),
                resolved=False,
            ),
        ]
    )
    sources = [
        hit(1, "m2", "Anita likes the pricing"),
        MemoryHit(
            memory_id="s",
            text="Sneha wants the SOC 2 report and residency answers",
            meeting_id="m3",
            meeting_date=date(2026, 8, 12),
            tags=[],
        ),
        hit(3, None, "SOC 2 unresolved meeting"),
    ]

    pairs = match_objection_sources(report, sources)

    assert [(o.raised_by, h.memory_id) for o, h in pairs] == [("Sneha", "s")]
