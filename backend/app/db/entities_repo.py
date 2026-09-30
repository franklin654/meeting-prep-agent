"""SQLite gateway for scheduling and entity creation."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlmodel import Session, col, select

from app.core.company import ae_contact_id
from app.core.errors import NotFoundError, ValidationError
from app.db.models import (
    Account,
    BriefRecord,
    Commitment,
    Contact,
    Meeting,
    MeetingAttendee,
    MeetingPrepared,
)
from app.schemas.enums import CommitmentStatus


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def create_account(session: Session, *, name: str, industry: str, stage: str) -> Account:
    row = Account(id=new_id("acc"), name=name, industry=industry, stage=stage)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def create_contact(
    session: Session, *, account_id: str, name: str, role: str | None, aliases: list[str]
) -> Contact:
    if session.get(Account, account_id) is None:
        raise NotFoundError(f"Account {account_id!r} not found.")
    row = Contact(id=new_id("c"), account_id=account_id, name=name, role=role, aliases=aliases)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def create_meeting(
    session: Session,
    *,
    account_id: str,
    title: str,
    scheduled_at: datetime,
    attendee_ids: list[str],
) -> Meeting:
    if session.get(Account, account_id) is None:
        raise NotFoundError(f"Account {account_id!r} not found.")
    contacts = [session.get(Contact, contact_id) for contact_id in attendee_ids]
    if any(
        contact is None or (contact.account_id != account_id and contact.id != ae_contact_id())
        for contact in contacts
    ):
        raise ValidationError("Meeting attendees must belong to the selected account or be our AE.")
    row = Meeting(
        id=new_id("m"),
        account_id=account_id,
        title=title,
        scheduled_at=scheduled_at,
        status="upcoming",
    )
    session.add(row)
    session.add_all(
        [MeetingAttendee(meeting_id=row.id, contact_id=contact_id) for contact_id in attendee_ids]
    )
    session.commit()
    session.refresh(row)
    return row


def list_account_meetings(session: Session, account_id: str) -> list[Meeting]:
    return list(session.exec(select(Meeting).where(Meeting.account_id == account_id)))


def attendees_for_meeting(session: Session, meeting_id: str) -> list[Contact]:
    rows = session.exec(
        select(Contact)
        .join(MeetingAttendee, col(MeetingAttendee.contact_id) == col(Contact.id))
        .where(MeetingAttendee.meeting_id == meeting_id)
        .order_by(col(Contact.name))
    )
    return list(rows)


def meeting_metrics(session: Session, meeting: Meeting) -> tuple[int, int, bool]:
    prior_done = [
        item
        for item in list_account_meetings(session, meeting.account_id)
        if item.status == "done" and item.scheduled_at < meeting.scheduled_at
    ]
    open_followups = session.exec(
        select(Commitment).where(
            Commitment.account_id == meeting.account_id,
            Commitment.status == CommitmentStatus.open,
        )
    ).all()
    has_history = any(
        item.status == "done" for item in list_account_meetings(session, meeting.account_id)
    )
    return len(open_followups), len(prior_done), has_history


def cancel_meeting(session: Session, meeting_id: str) -> None:
    meeting = session.get(Meeting, meeting_id)
    if meeting is None:
        raise NotFoundError(f"Meeting {meeting_id!r} not found.")
    if meeting.status != "upcoming" or meeting.transcript is not None:
        raise ValidationError("Only an upcoming meeting without a transcript can be cancelled.")
    for brief in session.exec(select(BriefRecord).where(BriefRecord.meeting_id == meeting_id)):
        session.delete(brief)
    for attendee in session.exec(
        select(MeetingAttendee).where(MeetingAttendee.meeting_id == meeting_id)
    ):
        session.delete(attendee)
    prepared = session.get(MeetingPrepared, meeting_id)
    if prepared is not None:
        session.delete(prepared)
    session.delete(meeting)
    session.commit()


def contact_metrics(session: Session, contact_id: str) -> tuple[int, int, date | None]:
    meeting_ids = list(
        session.exec(
            select(MeetingAttendee.meeting_id).where(MeetingAttendee.contact_id == contact_id)
        )
    )
    meetings = [session.get(Meeting, meeting_id) for meeting_id in meeting_ids]
    recorded = [meeting for meeting in meetings if meeting is not None]
    open_count = session.exec(
        select(Commitment).where(
            Commitment.contact_id == contact_id, Commitment.status == CommitmentStatus.open
        )
    ).all()
    last = max(
        (meeting.scheduled_at.date() for meeting in recorded if meeting.status == "done"),
        default=None,
    )
    return len(recorded), len(open_count), last


def list_contacts(session: Session, *, query: str | None, account_id: str | None) -> list[Contact]:
    statement = select(Contact)
    if account_id is not None:
        statement = statement.where(Contact.account_id == account_id)
    if query:
        statement = statement.where(col(Contact.name).ilike(f"%{query}%"))
    return list(session.exec(statement.order_by(col(Contact.name), col(Contact.id))))
