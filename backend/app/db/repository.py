"""All SQLite reads and writes (docs/technical-design.md "Backend modules").

Per AGENTS.md hard rule 1, this is the only module (besides `session.py`,
which only builds the engine/session) that touches a DB `Session`. Routers
and services get a `Session` from `app.db.session.get_session` as a FastAPI
dependency and call the functions below rather than issuing SQL themselves.

Functions take an explicit `session: Session` argument rather than opening
their own, so callers control transaction boundaries (e.g. a router commits
once per request across several repository calls where that matters).

Not every CRUD combination the app will eventually need is here — this
covers create/read/update for a representative set of the nine tables,
including the overdue-commitments query, and gives later tickets (T12+) a
real gateway to extend rather than a stub.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlmodel import Session, col, select

from app.core.errors import NotFoundError
from app.core.time import today
from app.db.models import (
    Account,
    AskAnswer,
    BriefRecord,
    Commitment,
    Contact,
    ContactPatternCache,
    ExtractedFact,
    Feedback,
    Job,
    Meeting,
    MeetingAttendee,
    MemoryOverride,
)
from app.schemas.enums import CommitmentStatus

# ---- Account ----


def create_account(session: Session, account: Account) -> Account:
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


def get_account(session: Session, account_id: str) -> Account | None:
    return session.get(Account, account_id)


def list_accounts(session: Session) -> list[Account]:
    return list(session.exec(select(Account)).all())


# ---- Contact ----


def create_contact(session: Session, contact: Contact) -> Contact:
    session.add(contact)
    session.commit()
    session.refresh(contact)
    return contact


def get_contact(session: Session, contact_id: str) -> Contact | None:
    return session.get(Contact, contact_id)


def list_contacts_for_account(session: Session, account_id: str) -> list[Contact]:
    statement = select(Contact).where(Contact.account_id == account_id)
    return list(session.exec(statement).all())


def update_contact(
    session: Session,
    contact_id: str,
    *,
    name: str | None = None,
    role: str | None = None,
    aliases: list[str] | None = None,
    needs_review: bool | None = None,
) -> Contact:
    contact = session.get(Contact, contact_id)
    if contact is None:
        raise NotFoundError(f"Contact {contact_id!r} not found.")
    if name is not None:
        contact.name = name
    if role is not None:
        contact.role = role
    if aliases is not None:
        contact.aliases = aliases
    if needs_review is not None:
        contact.needs_review = needs_review
    session.add(contact)
    session.commit()
    session.refresh(contact)
    return contact


# ---- Meeting ----


def create_meeting(session: Session, meeting: Meeting) -> Meeting:
    session.add(meeting)
    session.commit()
    session.refresh(meeting)
    return meeting


def get_meeting(session: Session, meeting_id: str) -> Meeting | None:
    return session.get(Meeting, meeting_id)


def list_meetings_for_account(session: Session, account_id: str) -> list[Meeting]:
    statement = select(Meeting).where(Meeting.account_id == account_id)
    return list(session.exec(statement).all())


def list_all_meetings(session: Session) -> list[Meeting]:
    statement = select(Meeting).order_by(col(Meeting.scheduled_at), col(Meeting.id))
    return list(session.exec(statement).all())


def list_all_extracted_facts(session: Session) -> list[ExtractedFact]:
    statement = select(ExtractedFact).order_by(col(ExtractedFact.created_at), col(ExtractedFact.id))
    return list(session.exec(statement).all())


def list_all_memory_overrides(session: Session) -> list[MemoryOverride]:
    statement = select(MemoryOverride).order_by(
        col(MemoryOverride.created_at), col(MemoryOverride.id)
    )
    return list(session.exec(statement).all())


def update_meeting_transcript(
    session: Session,
    meeting_id: str,
    *,
    transcript: str,
    ingested_at: datetime,
) -> Meeting:
    """Attach an ingested transcript to a meeting and mark it `done`."""
    meeting = session.get(Meeting, meeting_id)
    if meeting is None:
        raise NotFoundError(f"Meeting {meeting_id!r} not found.")
    meeting.transcript = transcript
    meeting.ingested_at = ingested_at
    meeting.status = "done"
    session.add(meeting)
    session.commit()
    session.refresh(meeting)
    return meeting


# ---- MeetingAttendee ----


def add_attendee(session: Session, meeting_id: str, contact_id: str) -> MeetingAttendee:
    attendee = MeetingAttendee(meeting_id=meeting_id, contact_id=contact_id)
    session.add(attendee)
    session.commit()
    session.refresh(attendee)
    return attendee


def list_attendees_for_meeting(session: Session, meeting_id: str) -> list[MeetingAttendee]:
    statement = select(MeetingAttendee).where(MeetingAttendee.meeting_id == meeting_id)
    return list(session.exec(statement).all())


# ---- Commitment ----


def create_commitment(session: Session, commitment: Commitment) -> Commitment:
    session.add(commitment)
    session.commit()
    session.refresh(commitment)
    return commitment


def get_commitment(session: Session, commitment_id: str) -> Commitment | None:
    return session.get(Commitment, commitment_id)


def list_commitments_for_account(session: Session, account_id: str) -> list[Commitment]:
    statement = select(Commitment).where(Commitment.account_id == account_id)
    return list(session.exec(statement).all())


def update_commitment(
    session: Session,
    commitment_id: str,
    *,
    status: CommitmentStatus | None = None,
    due_date: date | None = None,
    set_due_date: bool = False,
    text: str | None = None,
) -> Commitment:
    commitment = session.get(Commitment, commitment_id)
    if commitment is None:
        raise NotFoundError(f"Commitment {commitment_id!r} not found.")
    if status is not None:
        commitment.status = status
    if set_due_date:
        commitment.due_date = due_date
    if text is not None:
        commitment.text = text
    session.add(commitment)
    session.commit()
    session.refresh(commitment)
    return commitment


def delete_commitment(session: Session, commitment_id: str) -> None:
    commitment = session.get(Commitment, commitment_id)
    if commitment is None:
        raise NotFoundError(f"Commitment {commitment_id!r} not found.")
    session.delete(commitment)
    session.commit()


def get_contact_pattern_cache(session: Session, contact_id: str) -> ContactPatternCache | None:
    return session.get(ContactPatternCache, contact_id)


def save_contact_pattern_cache(
    session: Session, contact_id: str, patterns: list[dict[str, Any]], refreshed_at: datetime
) -> ContactPatternCache:
    cached = session.get(ContactPatternCache, contact_id)
    if cached is None:
        cached = ContactPatternCache(
            contact_id=contact_id, patterns=patterns, refreshed_at=refreshed_at
        )
    else:
        cached.patterns = patterns
        cached.refreshed_at = refreshed_at
    session.add(cached)
    session.commit()
    session.refresh(cached)
    return cached


def close_commitment(
    session: Session, commitment_id: str, *, closed_by_meeting_id: str
) -> Commitment:
    commitment = session.get(Commitment, commitment_id)
    if commitment is None:
        raise NotFoundError(f"Commitment {commitment_id!r} not found.")
    commitment.status = CommitmentStatus.done
    commitment.closed_by_meeting_id = closed_by_meeting_id
    session.add(commitment)
    session.commit()
    session.refresh(commitment)
    return commitment


def list_overdue_commitments(
    session: Session, *, account_id: str | None = None
) -> list[Commitment]:
    """Open commitments whose `due_date` is before `settings.demo_today`.

    "Overdue" is computed, never stored (docs/data-model-and-schemas.md):
    `status == open and due_date < settings.demo_today`. "Today" is read
    through `app.core.time.today()` per AGENTS.md hard rule 6, never
    `date.today()`, so this reflects the demo clock, not the real one.
    """
    statement = select(Commitment).where(
        Commitment.status == CommitmentStatus.open,
        Commitment.due_date.is_not(None),  # type: ignore[union-attr]
        Commitment.due_date < today(),  # type: ignore[operator]
    )
    if account_id is not None:
        statement = statement.where(Commitment.account_id == account_id)
    return list(session.exec(statement).all())


# ---- BriefRecord ----


def create_brief_record(session: Session, brief_record: BriefRecord) -> BriefRecord:
    session.add(brief_record)
    session.commit()
    session.refresh(brief_record)
    return brief_record


def get_brief_record(session: Session, brief_id: str) -> BriefRecord | None:
    return session.get(BriefRecord, brief_id)


def list_brief_records_for_meetings(session: Session, meeting_ids: list[str]) -> list[BriefRecord]:
    if not meeting_ids:
        return []
    statement = select(BriefRecord).where(col(BriefRecord.meeting_id).in_(meeting_ids))
    return list(session.exec(statement).all())


# ---- Feedback ----


def create_feedback(session: Session, feedback: Feedback) -> Feedback:
    session.add(feedback)
    session.commit()
    session.refresh(feedback)
    return feedback


def list_feedback_for_brief(session: Session, brief_id: str) -> list[Feedback]:
    statement = select(Feedback).where(Feedback.brief_id == brief_id)
    return list(session.exec(statement).all())


# ---- AskAnswer ----


def create_ask_answer(session: Session, ask_answer: AskAnswer) -> AskAnswer:
    session.add(ask_answer)
    session.commit()
    session.refresh(ask_answer)
    return ask_answer


def get_ask_answer(session: Session, ask_id: str) -> AskAnswer | None:
    return session.get(AskAnswer, ask_id)


def pin_ask_answer(session: Session, ask_id: str, *, meeting_id: str) -> AskAnswer:
    ask_answer = session.get(AskAnswer, ask_id)
    if ask_answer is None:
        raise NotFoundError(f"AskAnswer {ask_id!r} not found.")
    ask_answer.pinned_to_meeting_id = meeting_id
    session.add(ask_answer)
    session.commit()
    session.refresh(ask_answer)
    return ask_answer


def list_pinned_ask_answers_for_meeting(session: Session, meeting_id: str) -> list[AskAnswer]:
    statement = (
        select(AskAnswer)
        .where(AskAnswer.pinned_to_meeting_id == meeting_id)
        .order_by(col(AskAnswer.created_at), col(AskAnswer.id))
    )
    return list(session.exec(statement).all())


# ---- Job ----


def create_job(session: Session, job: Job) -> Job:
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def get_job(session: Session, job_id: str) -> Job | None:
    return session.get(Job, job_id)


def update_job_status(
    session: Session,
    job_id: str,
    *,
    status: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    finished_at: datetime | None = None,
) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise NotFoundError(f"Job {job_id!r} not found.")
    job.status = status
    if result is not None:
        job.result = result
    if error is not None:
        job.error = error
    if finished_at is not None:
        job.finished_at = finished_at
    session.add(job)
    session.commit()
    session.refresh(job)
    return job
