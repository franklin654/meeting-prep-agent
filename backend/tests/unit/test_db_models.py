"""T06: the nine SQLModel tables create cleanly and round-trip JSON/enum columns.

docs/data-model-and-schemas.md ("SQLite tables") is the source of truth for
field-for-field shape; these tests exercise that the tables actually work
against a real SQLite file (not mocked), per the ticket's "Done when".
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Session, SQLModel

from app.db.models import (
    Account,
    AskAnswer,
    BriefRecord,
    Commitment,
    Contact,
    Feedback,
    Job,
    Meeting,
    MeetingAttendee,
)
from app.schemas.brief import SectionKey
from app.schemas.enums import CommitmentStatus, Owner, ScopeType


def test_all_thirteen_tables_are_registered_on_metadata() -> None:
    table_names = set(SQLModel.metadata.tables.keys())
    assert table_names == {
        "account",
        "contact",
        "meeting",
        "meetingattendee",
        "commitment",
        "briefrecord",
        "feedback",
        "askanswer",
        "job",
        "extractedfact",
        "capturedraft",
        "meetingprepared",
        "memoryoverride",
    }


def test_contact_aliases_round_trip_as_json_list(session: Session) -> None:
    contact = Contact(id="c_rahul", account_id=None, name="Rahul", aliases=["RS", "Rahul S."])
    session.add(contact)
    session.commit()
    session.refresh(contact)

    fetched = session.get(Contact, "c_rahul")
    assert fetched is not None
    assert fetched.aliases == ["RS", "Rahul S."]


def test_commitment_enum_columns_round_trip(session: Session) -> None:
    account = Account(id="acc_finedge", name="FinEdge", industry="fintech", stage="evaluation")
    meeting = Meeting(
        id="m1_finedge",
        account_id="acc_finedge",
        title="Kickoff",
        scheduled_at=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
        status="done",
    )
    session.add(account)
    session.add(meeting)
    session.commit()

    commitment = Commitment(
        id="cm_abc123",
        account_id="acc_finedge",
        meeting_id="m1_finedge",
        owner=Owner.us,
        text="Send pricing deck",
        source_quote="I'll send the deck",
    )
    session.add(commitment)
    session.commit()
    session.refresh(commitment)

    fetched = session.get(Commitment, "cm_abc123")
    assert fetched is not None
    assert fetched.owner == Owner.us
    assert fetched.status == CommitmentStatus.open  # default


def test_brief_record_and_job_json_dict_columns_round_trip(session: Session) -> None:
    account = Account(id="acc_x", name="X", industry="tech", stage="discovery")
    meeting = Meeting(
        id="m_x",
        account_id="acc_x",
        title="Call",
        scheduled_at=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
        status="upcoming",
    )
    session.add(account)
    session.add(meeting)
    session.commit()

    brief = BriefRecord(
        id="br_1",
        meeting_id="m_x",
        mode="memory",
        content={"sections": {"agenda": []}},
        created_at=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
    )
    job = Job(
        id="job_1",
        kind="ingest",
        status="done",
        result={"facts": ["a"], "new_commitments": 1},
        created_at=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
    )
    session.add(brief)
    session.add(job)
    session.commit()
    session.refresh(brief)
    session.refresh(job)

    fetched_brief = session.get(BriefRecord, "br_1")
    fetched_job = session.get(Job, "job_1")
    assert fetched_brief is not None
    assert fetched_brief.content == {"sections": {"agenda": []}}
    assert fetched_job is not None
    assert fetched_job.result == {"facts": ["a"], "new_commitments": 1}


def test_feedback_section_key_and_askanswer_scope_type_round_trip(session: Session) -> None:
    account = Account(id="acc_y", name="Y", industry="tech", stage="discovery")
    meeting = Meeting(
        id="m_y",
        account_id="acc_y",
        title="Call",
        scheduled_at=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
        status="upcoming",
    )
    session.add(account)
    session.add(meeting)
    session.commit()

    brief = BriefRecord(
        id="br_2",
        meeting_id="m_y",
        mode="no_memory",
        content={},
        created_at=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
    )
    session.add(brief)
    session.commit()

    feedback = Feedback(
        id="fb_1",
        brief_id="br_2",
        section=SectionKey.open_commitments,
        action="up",
        created_at=datetime(2026, 8, 1, 9, 5, tzinfo=UTC),
    )
    ask_answer = AskAnswer(
        id="ask_1",
        scope_type=ScopeType.account,
        scope_id="acc_y",
        question="What is the budget?",
        answer={"answer": "…"},
        created_at=datetime(2026, 8, 1, 9, 6, tzinfo=UTC),
    )
    session.add(feedback)
    session.add(ask_answer)
    session.commit()
    session.refresh(feedback)
    session.refresh(ask_answer)

    fetched_feedback = session.get(Feedback, "fb_1")
    fetched_ask = session.get(AskAnswer, "ask_1")
    assert fetched_feedback is not None
    assert fetched_feedback.section == SectionKey.open_commitments
    assert fetched_ask is not None
    assert fetched_ask.scope_type == ScopeType.account


def test_meeting_attendee_is_a_composite_key_join_row(session: Session) -> None:
    account = Account(id="acc_z", name="Z", industry="tech", stage="discovery")
    contact = Contact(id="c_z", account_id="acc_z", name="Zed")
    meeting = Meeting(
        id="m_z",
        account_id="acc_z",
        title="Call",
        scheduled_at=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
        status="upcoming",
    )
    session.add(account)
    session.add(contact)
    session.add(meeting)
    session.commit()

    attendee = MeetingAttendee(meeting_id="m_z", contact_id="c_z")
    session.add(attendee)
    session.commit()

    fetched = session.get(MeetingAttendee, ("m_z", "c_z"))
    assert fetched is not None
