"""Queries behind the meetings/notes API (ticket T13).

Kept apart from `repository.py` (owned by T07) so the API lane adds read models and
`save_transcript` without editing that module. Like `repository.py` and `ingest_repo.py`,
this is a DB module: only these modules touch a `Session` (AGENTS.md hard rule 1).
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass

from sqlmodel import Session, col, select

from app.core.errors import NotFoundError
from app.db import brief_repo
from app.db.models import Account, BriefRecord, Contact, Meeting, MeetingAttendee


@dataclass(frozen=True)
class MeetingRow:
    """One meeting with everything `MeetingSummary` needs."""

    meeting: Meeting
    account_name: str
    attendees: list[Contact]
    brief_ready: bool


def list_meeting_rows(session: Session, status: str | None = None) -> list[MeetingRow]:
    """All meetings (optionally one status), oldest `scheduled_at` first."""
    statement = select(Meeting, Account.name).join(
        Account, col(Account.id) == col(Meeting.account_id)
    )
    if status is not None:
        statement = statement.where(Meeting.status == status)
    statement = statement.order_by(col(Meeting.scheduled_at), col(Meeting.id))
    found = list(session.exec(statement).all())
    if not found:
        return []

    ids = [m.id for m, _ in found]
    attendee_rows = session.exec(
        select(MeetingAttendee.meeting_id, Contact)
        .join(Contact, col(Contact.id) == col(MeetingAttendee.contact_id))
        .where(col(MeetingAttendee.meeting_id).in_(ids))
        .order_by(col(Contact.name))
    ).all()
    attendees: dict[str, list[Contact]] = {}
    for meeting_id, contact in attendee_rows:
        attendees.setdefault(meeting_id, []).append(contact)
    # `brief_ready` = a FRESH MEMORY brief exists: the exact rule GET /brief uses
    # (brief_repo.get_fresh_brief), applied only where a memory record exists.
    with_memory_brief = set(
        session.exec(
            select(BriefRecord.meeting_id)
            .where(col(BriefRecord.meeting_id).in_(ids), BriefRecord.mode == "memory")
            .distinct()
        ).all()
    )
    with_brief = {
        mid
        for mid in with_memory_brief
        if brief_repo.get_fresh_brief(lambda: nullcontext(session), mid, "memory") is not None
    }
    return [
        MeetingRow(
            meeting=m,
            account_name=name,
            attendees=attendees.get(m.id, []),
            brief_ready=m.id in with_brief,
        )
        for m, name in found
    ]


def save_transcript(session: Session, meeting_id: str, transcript: str) -> Meeting:
    """Store the transcript only. Ingest marks the meeting done, after the retain succeeded."""
    meeting = session.get(Meeting, meeting_id)
    if meeting is None:
        raise NotFoundError(f"Meeting {meeting_id!r} not found.")
    meeting.transcript = transcript
    session.add(meeting)
    session.commit()
    session.refresh(meeting)
    return meeting
