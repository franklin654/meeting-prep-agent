"""Shared FinEdge-like fixture world for the brief tests (no network).

SQLite holds M1..M5 (done) and M6 (upcoming) plus a ledger; `FakeMemoryService` holds
retained facts of both Hindsight kinds (`world` with metadata, `observation` without),
a mental model and a queued R1 reflect result. `ScriptedLLM` builds its `BriefDraft`
from the rendered prompt, because the short evidence ids (`mem:3`) are assigned in code.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlmodel import Session, SQLModel, create_engine

from app.db.brief_repo import SessionFactory
from app.db.models import Account, Commitment, Contact, Meeting, MeetingAttendee
from app.memory.tags import account_tag, contact_tag, fact_kind_tag, meeting_tag
from app.schemas.brief import BriefDraft, DraftItem, SectionKey, Severity
from app.schemas.enums import CommitmentStatus, FactKind, Owner
from app.schemas.memory import MemoryHit, ReflectResult
from tests.fakes.fake_llm import FakeLLM, RecordedCall
from tests.fakes.fake_memory_service import FakeMemoryService

T = TypeVar("T", bound=BaseModel)

ACC = "acc_finedge"
DECK_QUOTE = "I'll get you a revised pricing deck with the pilot option by the 3rd"

MEETINGS = {
    "m1_finedge": (date(2026, 7, 14), "Discovery", ["c_priya", "c_rahul", "c_karan"]),
    "m2_finedge": (date(2026, 7, 28), "Budget and process", ["c_priya", "c_karan", "c_anita"]),
    "m3_finedge": (
        date(2026, 8, 12),
        "Technical deep dive",
        ["c_priya", "c_rahul", "c_karan"],
    ),
    "m4_finedge": (date(2026, 8, 27), "Pilot scoping", ["c_priya", "c_rahul", "c_karan"]),
    "m5_finedge": (date(2026, 9, 15), "Check-in", ["c_priya", "c_karan"]),
}
M6 = "m6_finedge"

RAHUL_M4_LINE = "Thanks Priya, let's get straight into the pilot scope."
ANITA_M2_LINE = "Numbers first please, what does this replace?"


def transcript_for(meeting_id: str) -> str:
    d = MEETINGS[meeting_id][0]
    lines = {
        "m2_finedge": [
            ("Priya Nair", "Account Executive", "Tracewise", "Thanks for joining."),
            ("Anita Desai", "CFO", "FinEdge Payments", ANITA_M2_LINE),
        ],
        "m4_finedge": [
            ("Priya Nair", "Account Executive", "Tracewise", "Hi all, welcome."),
            ("Rahul Mehta", "VP Engineering", "FinEdge Payments", RAHUL_M4_LINE),
            ("Priya Nair", "Account Executive", "Tracewise", DECK_QUOTE),
        ],
    }.get(
        meeting_id,
        [("Priya Nair", "Account Executive", "Tracewise", "Hello.")],
    )
    return "\n".join(
        f"[{d.isoformat()}T10:00:{i * 7:02d}+05:30] {n} ({r}, {c}): {t}"
        for i, (n, r, c, t) in enumerate(lines)
    )


class World:
    """Everything a brief test needs, plus handles for mutating it."""

    def __init__(self, engine: Any, memory: FakeMemoryService) -> None:
        self.engine = engine
        self.memory = memory
        self.session_factory: SessionFactory = lambda: Session(engine)


def _seed_sql(engine: Any) -> None:
    with Session(engine) as s:
        s.add(
            Account(
                id=ACC,
                name="FinEdge Payments",
                industry="Fintech",
                stage="evaluation",
                deal_value_usd=40000,
            )
        )
        s.add(Contact(id="c_priya", account_id=None, name="Priya Nair", role="Account Executive"))
        for cid, name, role in [
            ("c_rahul", "Rahul Mehta", "VP Engineering"),
            ("c_karan", "Karan Shah", "Data Platform Lead"),
            ("c_anita", "Anita Desai", "CFO"),
            ("c_newbie", "Vikram Rao", "CTO"),
        ]:
            s.add(Contact(id=cid, account_id=ACC, name=name, role=role))
        for mid, (d, title, attendees) in MEETINGS.items():
            s.add(
                Meeting(
                    id=mid,
                    account_id=ACC,
                    title=title,
                    scheduled_at=datetime(d.year, d.month, d.day, 10, 0, tzinfo=UTC),
                    status="done",
                    transcript=transcript_for(mid),
                    ingested_at=datetime(d.year, d.month, d.day, 12, 0, tzinfo=UTC),
                )
            )
            for cid in attendees:
                s.add(MeetingAttendee(meeting_id=mid, contact_id=cid))
        s.add(
            Meeting(
                id=M6,
                account_id=ACC,
                title="Pilot decision",
                scheduled_at=datetime(2026, 9, 29, 10, 0, tzinfo=UTC),
                status="upcoming",
            )
        )
        for cid in ["c_priya", "c_rahul", "c_anita", "c_karan", "c_newbie"]:
            s.add(MeetingAttendee(meeting_id=M6, contact_id=cid))
        s.add(
            Commitment(
                id="cm_deck",
                account_id=ACC,
                meeting_id="m4_finedge",
                owner=Owner.us,
                contact_id="c_rahul",
                text="Send revised pricing deck with pilot option",
                due_date=date(2026, 9, 3),
                status=CommitmentStatus.open,
                source_quote=DECK_QUOTE,
            )
        )
        s.add(
            Commitment(
                id="cm_dag",
                account_id=ACC,
                meeting_id="m4_finedge",
                owner=Owner.us,
                text="Share DAG configs",
                due_date=date(2026, 9, 5),
                status=CommitmentStatus.done,
                source_quote="I'll share the DAG configs",
                closed_by_meeting_id="m5_finedge",
            )
        )
        s.commit()


def _seed_memory(memory: FakeMemoryService) -> None:
    memory.seed_mental_model(
        f"relationship-{ACC}",
        name="Relationship: FinEdge",
        content="Evaluation stage. Budget about $40K. Pilot scoping agreed; deck outstanding.",
    )
    # world fact with metadata (M1, Rahul, personal)
    memory.seed_fact(
        "w_ananya",
        "Rahul's daughter Ananya starts college in Pune in September",
        tags=[
            account_tag(ACC),
            contact_tag("c_rahul"),
            meeting_tag("m1_finedge"),
            fact_kind_tag(FactKind.personal),
        ],
        meeting_id="m1_finedge",
        meeting_date=date(2026, 7, 14),
    )
    # observation: empty metadata, meeting only via tag + mentioned_at (M5, Karan)
    memory.seed_fact(
        "o_move",
        "Karan said Ananya's move to Pune is keeping Rahul busy",
        tags=[
            account_tag(ACC),
            contact_tag("c_karan"),
            meeting_tag("m5_finedge"),
            fact_kind_tag(FactKind.personal),
        ],
        memory_type="observation",
        mentioned_at=date(2026, 9, 15),
    )
    memory.seed_fact(
        "w_datahawk",
        "DataHawk was mentioned as a cheaper competitor without India residency",
        tags=[
            account_tag(ACC),
            contact_tag("c_rahul"),
            meeting_tag("m3_finedge"),
            fact_kind_tag(FactKind.competitor),
        ],
        meeting_id="m3_finedge",
        meeting_date=date(2026, 8, 12),
    )
    # Recalled unresolved objection evidence used directly by P3.
    memory.seed_fact(
        "o_sec",
        "Sneha raised a concern about the SOC 2 report and data residency",
        tags=[account_tag(ACC), meeting_tag("m3_finedge"), fact_kind_tag(FactKind.objection)],
        memory_type="observation",
        mentioned_at=date(2026, 8, 12),
    )


def queue_objections(memory: FakeMemoryService) -> None:
    memory.queue_reflect_response(
        ReflectResult(
            text="objections",
            structured={
                "objections": [
                    {
                        "concern": "SOC 2 report and data residency",
                        "raised_by": "Sneha",
                        "raised_on": "2026-08-12",
                        "resolved": False,
                        "resolution": None,
                    },
                    {
                        "concern": "Pipeline limit on Growth plan",
                        "raised_by": "Karan",
                        "raised_on": "2026-07-14",
                        "resolved": True,
                        "resolution": "Enterprise",
                    },
                ]
            },
            sources=[
                MemoryHit(
                    memory_id="o_sec",
                    text="Sneha raised a concern about the SOC 2 report and data residency",
                    meeting_id=None,
                    meeting_date=None,
                    tags=[],
                )
            ],
            structured_error=None,
        )
    )


def make_world(tmp_path: Path) -> Iterator[World]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'brief.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    _seed_sql(engine)
    memory = FakeMemoryService()
    _seed_memory(memory)
    queue_objections(memory)
    yield World(engine, memory)
    engine.dispose()


# ---- LLM ---------------------------------------------------------------------------


def evidence_ids(prompt: str, needle: str) -> list[str]:
    """Short ids of every evidence line in the rendered prompt containing `needle`."""
    return [
        m.group(1)
        for m in re.finditer(r"^\[((?:mm|mem|led|ask):\d+)\](.*)$", prompt, re.MULTILINE)
        if needle.lower() in m.group(2).lower()
    ]


class ScriptedLLM(FakeLLM):
    """`FakeLLM` (records calls) whose draft is built from the prompt it receives."""

    def __init__(self, build: Callable[[str], BriefDraft]) -> None:
        super().__init__()
        self._build = build

    async def complete_json(
        self,
        prompt: str,
        schema: type[T],
        *,
        temperature: float = 0.0,
        system: str | None = None,
    ) -> T:
        self.calls.append(
            RecordedCall(prompt=prompt, schema=schema, temperature=temperature, system=system)
        )
        draft = self._build(prompt)
        assert isinstance(draft, schema)
        return draft


def item(
    text: str,
    ids: list[str],
    severity: Severity = Severity.info,
    contact_ids: list[str] | None = None,
) -> DraftItem:
    return DraftItem(text=text, severity=severity, contact_ids=contact_ids or [], evidence_ids=ids)


def good_draft(prompt: str, deck_severity: Severity = Severity.warning) -> BriefDraft:
    return BriefDraft(
        sections={
            SectionKey.where_left_off: [
                item("Pilot scoping agreed", evidence_ids(prompt, "Relationship"))
            ],
            SectionKey.open_commitments: [
                item(
                    "Send the revised pricing deck",
                    evidence_ids(prompt, "pricing deck"),
                    deck_severity,
                    ["c_rahul"],
                )
            ],
            SectionKey.unresolved_objections: [
                item("Security review: SOC 2 and residency", evidence_ids(prompt, "Unresolved"))
            ],
            SectionKey.personal_touchpoints: [
                item(
                    "Ask Rahul how Ananya's move to Pune is going",
                    evidence_ids(prompt, "Ananya"),
                    contact_ids=["c_rahul"],
                )
            ],
            SectionKey.watch_outs: [item("DataHawk is cheaper", evidence_ids(prompt, "DataHawk"))],
            SectionKey.agenda: [item("Confirm pilot start", evidence_ids(prompt, "pricing deck"))],
        }
    )
