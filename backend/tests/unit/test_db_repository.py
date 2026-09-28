"""T06: CRUD tests for `app.db.repository`, and the overdue-commitments query.

The overdue test is the ticket's specific "Done when": it must prove the
query reads `settings.demo_today` (via `app.core.time.today()`), not the
real clock, by moving `demo_today` with `monkeypatch` and watching the
result change — same pattern as `tests/unit/test_time.py`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlmodel import Session

from app import config
from app.core.errors import NotFoundError
from app.db import repository as repo
from app.db.models import Account, AskAnswer, BriefRecord, Commitment, Contact, Job, Meeting
from app.schemas.enums import CommitmentStatus, Owner, ScopeType


def _make_account(session: Session, account_id: str = "acc_finedge") -> Account:
    return repo.create_account(
        session,
        Account(id=account_id, name="FinEdge", industry="fintech", stage="evaluation"),
    )


def _make_meeting(session: Session, account_id: str, meeting_id: str) -> Meeting:
    return repo.create_meeting(
        session,
        Meeting(
            id=meeting_id,
            account_id=account_id,
            title="Kickoff",
            scheduled_at=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
            status="upcoming",
        ),
    )


# ---- Account ----


def test_create_and_get_account(session: Session) -> None:
    created = _make_account(session)

    fetched = repo.get_account(session, "acc_finedge")

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.name == "FinEdge"


def test_get_account_missing_returns_none(session: Session) -> None:
    assert repo.get_account(session, "acc_nope") is None


def test_list_accounts(session: Session) -> None:
    _make_account(session, "acc_a")
    _make_account(session, "acc_b")

    accounts = repo.list_accounts(session)

    assert {a.id for a in accounts} == {"acc_a", "acc_b"}


# ---- Contact ----


def test_create_read_update_contact(session: Session) -> None:
    _make_account(session)
    repo.create_contact(session, Contact(id="c_rahul", account_id="acc_finedge", name="Rahul"))

    updated = repo.update_contact(session, "c_rahul", role="CTO", needs_review=True)

    assert updated.role == "CTO"
    assert updated.needs_review is True
    fetched = repo.get_contact(session, "c_rahul")
    assert fetched is not None
    assert fetched.role == "CTO"


def test_update_contact_missing_raises_not_found(session: Session) -> None:
    with pytest.raises(NotFoundError):
        repo.update_contact(session, "c_nope", role="CTO")


def test_list_contacts_for_account(session: Session) -> None:
    _make_account(session)
    repo.create_contact(session, Contact(id="c_1", account_id="acc_finedge", name="A"))
    repo.create_contact(session, Contact(id="c_2", account_id="acc_finedge", name="B"))
    repo.create_contact(session, Contact(id="c_3", account_id=None, name="Us"))

    contacts = repo.list_contacts_for_account(session, "acc_finedge")

    assert {c.id for c in contacts} == {"c_1", "c_2"}


# ---- Meeting ----


def test_create_read_meeting_and_update_transcript(session: Session) -> None:
    _make_account(session)
    _make_meeting(session, "acc_finedge", "m1_finedge")

    updated = repo.update_meeting_transcript(
        session,
        "m1_finedge",
        transcript="hello world " * 10,
        ingested_at=datetime(2026, 8, 1, 11, 0, tzinfo=UTC),
    )

    assert updated.status == "done"
    assert updated.transcript is not None
    fetched = repo.get_meeting(session, "m1_finedge")
    assert fetched is not None
    assert fetched.ingested_at == datetime(2026, 8, 1, 11, 0, tzinfo=UTC)


def test_update_meeting_transcript_missing_raises_not_found(session: Session) -> None:
    with pytest.raises(NotFoundError):
        repo.update_meeting_transcript(
            session, "m_nope", transcript="x", ingested_at=datetime(2026, 8, 1, tzinfo=UTC)
        )


def test_list_meetings_for_account(session: Session) -> None:
    _make_account(session)
    _make_meeting(session, "acc_finedge", "m1_finedge")
    _make_meeting(session, "acc_finedge", "m2_finedge")

    meetings = repo.list_meetings_for_account(session, "acc_finedge")

    assert {m.id for m in meetings} == {"m1_finedge", "m2_finedge"}


# ---- MeetingAttendee ----


def test_add_and_list_attendees(session: Session) -> None:
    _make_account(session)
    _make_meeting(session, "acc_finedge", "m1_finedge")
    repo.create_contact(session, Contact(id="c_rahul", account_id="acc_finedge", name="Rahul"))

    repo.add_attendee(session, "m1_finedge", "c_rahul")

    attendees = repo.list_attendees_for_meeting(session, "m1_finedge")
    assert [a.contact_id for a in attendees] == ["c_rahul"]


# ---- Commitment + overdue query ----


def _make_commitment(
    session: Session,
    commitment_id: str,
    *,
    due_date: date | None,
    status: str | None = None,
) -> Commitment:
    commitment = Commitment(
        id=commitment_id,
        account_id="acc_finedge",
        meeting_id="m1_finedge",
        owner=Owner.us,
        text="Send pricing deck",
        due_date=due_date,
        source_quote="I'll send it",
    )
    if status is not None:
        commitment.status = CommitmentStatus(status)
    return repo.create_commitment(session, commitment)


def test_create_get_and_close_commitment(session: Session) -> None:
    _make_account(session)
    _make_meeting(session, "acc_finedge", "m1_finedge")
    _make_commitment(session, "cm_1", due_date=date(2026, 8, 10))

    closed = repo.close_commitment(session, "cm_1", closed_by_meeting_id="m1_finedge")

    assert closed.status.value == "done"
    assert closed.closed_by_meeting_id == "m1_finedge"


def test_close_commitment_missing_raises_not_found(session: Session) -> None:
    with pytest.raises(NotFoundError):
        repo.close_commitment(session, "cm_nope", closed_by_meeting_id="m1_finedge")


def test_list_commitments_for_account(session: Session) -> None:
    _make_account(session)
    _make_meeting(session, "acc_finedge", "m1_finedge")
    _make_commitment(session, "cm_1", due_date=date(2026, 8, 10))
    _make_commitment(session, "cm_2", due_date=None)

    commitments = repo.list_commitments_for_account(session, "acc_finedge")

    assert {c.id for c in commitments} == {"cm_1", "cm_2"}


def test_overdue_commitments_uses_demo_today_not_real_clock(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Genuinely proves the query reads `settings.demo_today`.

    With `demo_today` set to 2026-08-15: a commitment due 2026-08-01 is
    overdue, one due 2026-08-20 is not. Moving `demo_today` forward past
    2026-08-20 must flip the second commitment to overdue too — if the code
    used `date.today()` instead, this assertion would fail (or pass only by
    the accident of when the test happens to run).
    """
    _make_account(session)
    _make_meeting(session, "acc_finedge", "m1_finedge")
    _make_commitment(session, "cm_overdue", due_date=date(2026, 8, 1))
    _make_commitment(session, "cm_future", due_date=date(2026, 8, 20))
    _make_commitment(session, "cm_no_due_date", due_date=None)
    _make_commitment(session, "cm_done_but_overdue", due_date=date(2026, 8, 1), status="done")

    monkeypatch.setattr(config.settings, "demo_today", date(2026, 8, 15))
    overdue_ids = {c.id for c in repo.list_overdue_commitments(session)}
    assert overdue_ids == {"cm_overdue"}

    monkeypatch.setattr(config.settings, "demo_today", date(2026, 8, 25))
    overdue_ids = {c.id for c in repo.list_overdue_commitments(session)}
    assert overdue_ids == {"cm_overdue", "cm_future"}


def test_overdue_commitments_filters_by_account(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_account(session, "acc_a")
    _make_account(session, "acc_b")
    _make_meeting(session, "acc_a", "m_a")
    _make_meeting(session, "acc_b", "m_b")
    repo.create_commitment(
        session,
        Commitment(
            id="cm_a",
            account_id="acc_a",
            meeting_id="m_a",
            owner=Owner.us,
            text="x",
            due_date=date(2026, 1, 1),
            source_quote="q",
        ),
    )
    repo.create_commitment(
        session,
        Commitment(
            id="cm_b",
            account_id="acc_b",
            meeting_id="m_b",
            owner=Owner.us,
            text="x",
            due_date=date(2026, 1, 1),
            source_quote="q",
        ),
    )

    monkeypatch.setattr(config.settings, "demo_today", date(2026, 6, 1))

    overdue = repo.list_overdue_commitments(session, account_id="acc_a")
    assert {c.id for c in overdue} == {"cm_a"}


# ---- BriefRecord / Feedback / AskAnswer / Job ----


def test_create_and_get_brief_record(session: Session) -> None:
    _make_account(session)
    _make_meeting(session, "acc_finedge", "m1_finedge")

    created = repo.create_brief_record(
        session,
        BriefRecord(
            id="br_1",
            meeting_id="m1_finedge",
            mode="memory",
            content={"sections": {}},
            created_at=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
        ),
    )

    fetched = repo.get_brief_record(session, created.id)
    assert fetched is not None
    assert fetched.mode == "memory"


def test_create_ask_answer_and_pin(session: Session) -> None:
    _make_account(session)
    _make_meeting(session, "acc_finedge", "m1_finedge")

    repo.create_ask_answer(
        session,
        AskAnswer(
            id="ask_1",
            scope_type=ScopeType.account,
            scope_id="acc_finedge",
            question="What's the budget?",
            answer={"answer": "…"},
            created_at=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
        ),
    )

    pinned = repo.pin_ask_answer(session, "ask_1", meeting_id="m1_finedge")

    assert pinned.pinned_to_meeting_id == "m1_finedge"


def test_pin_ask_answer_missing_raises_not_found(session: Session) -> None:
    with pytest.raises(NotFoundError):
        repo.pin_ask_answer(session, "ask_nope", meeting_id="m1_finedge")


def test_create_job_and_update_status(session: Session) -> None:
    job = Job(
        id="job_1", kind="ingest", status="pending", created_at=datetime(2026, 8, 1, tzinfo=UTC)
    )
    created = repo.create_job(session, job)
    assert created.status == "pending"

    updated = repo.update_job_status(
        session,
        "job_1",
        status="done",
        result={"facts": []},
        finished_at=datetime(2026, 8, 1, 0, 5, tzinfo=UTC),
    )

    assert updated.status == "done"
    assert updated.result == {"facts": []}
    fetched = repo.get_job(session, "job_1")
    assert fetched is not None
    assert fetched.finished_at == datetime(2026, 8, 1, 0, 5, tzinfo=UTC)


def test_update_job_status_missing_raises_not_found(session: Session) -> None:
    with pytest.raises(NotFoundError):
        repo.update_job_status(session, "job_nope", status="failed")
