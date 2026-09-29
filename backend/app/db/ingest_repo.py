"""SQLite reads and writes used by the ingest service (T12).

Kept separate from `app/db/repository.py` (owned by an earlier ticket) so ingest can
add what it needs without editing that file. Same conventions: `session` first, each
call commits, and only DB modules touch a `Session` (AGENTS.md hard rule 1).

Timestamps: record-keeping stamps (`ingested_at`, job `created_at`/`finished_at`) use the
wall clock `app.core.time.utcnow()` so cache invalidation can compare them; business dates
still come from `today()`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from sqlmodel import Session, col, select

from app.core.errors import NotFoundError
from app.core.time import utcnow
from app.db import repository
from app.db.models import Account, Commitment, Contact, Job, Meeting, MeetingAttendee
from app.schemas.enums import CommitmentStatus, Owner


def stamp() -> datetime:
    """Record-keeping timestamp: the tz-aware wall clock (see `app.core.time.utcnow`)."""
    return utcnow()


def new_id(prefix: str) -> str:
    """`<prefix>_<uuid8>` per docs/data-model-and-schemas.md "Conventions"."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ---- meeting ----


def get_meeting_with_attendees(session: Session, meeting_id: str) -> tuple[Meeting, list[Contact]]:
    meeting = session.get(Meeting, meeting_id)
    if meeting is None:
        raise NotFoundError(f"Meeting {meeting_id!r} not found.")
    statement = (
        select(Contact)
        .join(MeetingAttendee, col(MeetingAttendee.contact_id) == col(Contact.id))
        .where(MeetingAttendee.meeting_id == meeting_id)
    )
    return meeting, list(session.exec(statement).all())


def set_meeting_ingested(session: Session, meeting_id: str, at: datetime) -> Meeting:
    meeting = session.get(Meeting, meeting_id)
    if meeting is None:
        raise NotFoundError(f"Meeting {meeting_id!r} not found.")
    meeting.status = "done"
    meeting.ingested_at = at
    session.add(meeting)
    session.commit()
    session.refresh(meeting)
    return meeting


# ---- account ----


def update_account_deal_value(session: Session, account_id: str, usd: int) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise NotFoundError(f"Account {account_id!r} not found.")
    account.deal_value_usd = usd
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


# ---- contacts ----


def list_contacts_for_matching(session: Session, account_id: str) -> list[Contact]:
    """The account's contacts plus our own people (`account_id is None`)."""
    statement = select(Contact).where(
        (col(Contact.account_id) == account_id) | col(Contact.account_id).is_(None)
    )
    return list(session.exec(statement).all())


# ---- commitments ----


def list_open_commitments(
    session: Session,
    account_id: str,
    *,
    before: datetime | None = None,
    exclude_meeting_id: str | None = None,
) -> list[Commitment]:
    """Open commitments for the account; with `before`, only those created by meetings
    scheduled strictly before it (the ones a new meeting's acknowledgements may close).
    """
    statement = select(Commitment).where(
        Commitment.account_id == account_id,
        Commitment.status == CommitmentStatus.open,
    )
    if exclude_meeting_id is not None:
        statement = statement.where(Commitment.meeting_id != exclude_meeting_id)
    if before is not None:
        statement = statement.join(Meeting, col(Meeting.id) == col(Commitment.meeting_id)).where(
            Meeting.scheduled_at < before
        )
    return list(session.exec(statement.order_by(col(Commitment.id))).all())


def mark_commitment_done(
    session: Session, commitment_id: str, closed_by_meeting_id: str
) -> Commitment:
    return repository.close_commitment(
        session, commitment_id, closed_by_meeting_id=closed_by_meeting_id
    )


def create_commitment_rows(
    session: Session,
    *,
    account_id: str,
    meeting_id: str,
    rows: Sequence[tuple[Owner, str | None, str, date | None, str]],
) -> list[Commitment]:
    """Insert open commitments; each row is `(owner, contact_id, text, due_date, quote)`."""
    created = [
        Commitment(
            id=new_id("cm"),
            account_id=account_id,
            meeting_id=meeting_id,
            owner=owner,
            contact_id=contact_id,
            text=text,
            due_date=due_date,
            status=CommitmentStatus.open,
            source_quote=quote,
        )
        for owner, contact_id, text, due_date, quote in rows
    ]
    session.add_all(created)
    session.commit()
    for commitment in created:
        session.refresh(commitment)
    return created


def delete_commitments_for_meeting(session: Session, meeting_id: str) -> int:
    rows = session.exec(select(Commitment).where(Commitment.meeting_id == meeting_id)).all()
    for row in rows:
        session.delete(row)
    session.commit()
    return len(rows)


def reopen_commitments_closed_by(session: Session, meeting_id: str) -> int:
    rows = session.exec(
        select(Commitment).where(Commitment.closed_by_meeting_id == meeting_id)
    ).all()
    for row in rows:
        row.status = CommitmentStatus.open
        row.closed_by_meeting_id = None
        session.add(row)
    session.commit()
    return len(rows)


# ---- jobs ----


def create_job_row(session: Session, kind: str = "ingest") -> Job:
    job = Job(id=new_id("job"), kind=kind, status="pending", created_at=stamp())
    return repository.create_job(session, job)


def finish_job(
    session: Session,
    job_id: str,
    *,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> Job:
    """Mark a job `done` (with `result`) or `failed` (with an error code)."""
    status = "failed" if error is not None else "done"
    return repository.update_job_status(
        session, job_id, status=status, result=result, error=error, finished_at=stamp()
    )
