"""SQLite reads and writes for the brief service (T14).

Kept in its own module so `repository.py` stays untouched; it reuses that module's
read functions inside one session per call. Functions take a `session_factory`
(e.g. `lambda: Session(engine)`) and return plain loaded objects, so services never
hold a session.

Timestamps on `BriefRecord` come from the REAL wall clock, not `settings.demo_today`:
ingest sets `Meeting.ingested_at` from the real clock, and cache invalidation compares
the two (a brief pinned to the demo date could never be invalidated by a live ingest).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.errors import NotFoundError
from app.core.time import utcnow
from app.db import repository
from app.db.facts_repo import list_account_facts
from app.db.models import (
    Account,
    AskAnswer,
    BriefRecord,
    Commitment,
    Contact,
    ExtractedFact,
    Meeting,
)
from app.db.overrides_repo import list_overrides
from app.schemas.brief import Brief
from app.schemas.enums import CommitmentStatus

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractContextManager[Session]]


def as_utc(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; treat naive as UTC so values compare."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass
class BriefInputs:
    meeting: Meeting
    account: Account
    attendees: list[Contact]  # everyone on the meeting, ours included
    account_meetings: list[Meeting]
    all_meetings: list[Meeting]
    other_accounts: list[Account]
    account_contacts: list[Contact]
    attendee_ids_by_meeting: dict[str, set[str]]  # for every account meeting
    open_commitments: list[Commitment]
    pinned_ask_answers: list[AskAnswer]
    extracted_facts: list[ExtractedFact] = field(default_factory=list)
    hidden_fact_ids: set[str] = field(default_factory=set)
    hidden_memory_ids: set[str] = field(default_factory=set)
    first_meeting: bool = False


def load_brief_inputs(
    session_factory: SessionFactory, meeting_id: str, *, include_ledger: bool = True
) -> BriefInputs:
    with session_factory() as session:
        meeting = repository.get_meeting(session, meeting_id)
        if meeting is None:
            raise NotFoundError(f"Meeting {meeting_id!r} not found.")
        account = repository.get_account(session, meeting.account_id)
        if account is None:
            raise NotFoundError(f"Account {meeting.account_id!r} not found.")

        account_meetings = repository.list_meetings_for_account(session, account.id)
        first_meeting = not any(
            prior.id != meeting.id
            and prior.status == "done"
            and prior.scheduled_at < meeting.scheduled_at
            for prior in account_meetings
        )
        read_memory_evidence = include_ledger and not first_meeting
        accounts = repository.list_accounts(session)
        other_accounts = [candidate for candidate in accounts if candidate.id != account.id]
        all_meetings = list(account_meetings)
        for other_account in other_accounts:
            all_meetings.extend(repository.list_meetings_for_account(session, other_account.id))
        account_contacts = repository.list_contacts_for_account(session, account.id)
        attendee_ids_by_meeting = {
            m.id: {a.contact_id for a in repository.list_attendees_for_meeting(session, m.id)}
            for m in account_meetings
        }
        attendees = [
            contact
            for contact_id in sorted(attendee_ids_by_meeting.get(meeting_id, set()))
            if (contact := repository.get_contact(session, contact_id)) is not None
        ]
        # no_memory briefs make no ledger reads at all.
        open_commitments = (
            [
                c
                for c in repository.list_commitments_for_account(session, account.id)
                if c.status == CommitmentStatus.open
            ]
            if read_memory_evidence
            else []
        )
        return BriefInputs(
            meeting=meeting,
            account=account,
            attendees=attendees,
            account_meetings=account_meetings,
            all_meetings=all_meetings,
            other_accounts=other_accounts,
            account_contacts=account_contacts,
            attendee_ids_by_meeting=attendee_ids_by_meeting,
            open_commitments=open_commitments,
            pinned_ask_answers=(
                repository.list_pinned_ask_answers_for_meeting(session, meeting_id)
                if read_memory_evidence
                else []
            ),
            extracted_facts=(
                list_account_facts(session, account.id) if read_memory_evidence else []
            ),
            hidden_fact_ids=(
                {
                    override.target_id
                    for override in list_overrides(session, target_type="fact")
                    if override.action in {"hidden", "corrected"}
                }
                if read_memory_evidence
                else set()
            ),
            hidden_memory_ids=(
                {
                    override.target_id
                    for override in list_overrides(session, target_type="memory")
                    if override.action in {"hidden", "corrected"}
                }
                if read_memory_evidence
                else set()
            ),
            first_meeting=first_meeting,
        )


def _find_record(session: Session, meeting_id: str, mode: str) -> BriefRecord | None:
    statement = select(BriefRecord).where(
        BriefRecord.meeting_id == meeting_id, BriefRecord.mode == mode
    )
    return session.exec(statement).first()


def new_brief_stamp(
    session_factory: SessionFactory, meeting_id: str, mode: str
) -> tuple[str, datetime]:
    """`(brief_id, generated_at)` for a brief about to be built.

    Reuses the id of an existing record for this meeting and mode, so Feedback rows
    pointing at it stay valid when the brief is regenerated.
    """
    with session_factory() as session:
        record = _find_record(session, meeting_id, mode)
        brief_id = record.id if record is not None else f"br_{uuid.uuid4().hex[:8]}"
    return brief_id, utcnow()


def save_brief(session_factory: SessionFactory, brief: Brief) -> Brief:
    """Upsert the record for `(brief.meeting_id, brief.mode)`; created_at = generated_at.

    Safe under concurrent calls for the same meeting and mode: the unique index turns the
    losing insert into an IntegrityError, which is rolled back and turned into an UPDATE of
    the existing row. Returns the brief carrying the STORED id (stable across regeneration).
    """
    with session_factory() as session:
        record = _find_record(session, brief.meeting_id, brief.mode)
        if record is None:
            session.add(
                BriefRecord(
                    id=brief.id,
                    meeting_id=brief.meeting_id,
                    mode=brief.mode,
                    content=brief.model_dump(mode="json"),
                    created_at=brief.generated_at,
                )
            )
            try:
                session.commit()
                return brief
            except IntegrityError:
                session.rollback()
                logger.info(
                    "brief.save_conflict meeting=%s mode=%s: updating existing row",
                    brief.meeting_id,
                    brief.mode,
                )
                record = _find_record(session, brief.meeting_id, brief.mode)
                if record is None:  # the conflicting row vanished: not a unique conflict
                    raise
        stored = brief.model_copy(update={"id": record.id})
        record.content = stored.model_dump(mode="json")
        record.created_at = stored.generated_at
        session.add(record)
        session.commit()
        return stored


def get_fresh_brief(session_factory: SessionFactory, meeting_id: str, mode: str) -> Brief | None:
    """The stored brief, unless the account has ingested a meeting since it was created."""
    with session_factory() as session:
        record = _find_record(session, meeting_id, mode)
        if record is None:
            return None
        meeting = repository.get_meeting(session, meeting_id)
        if meeting is None:
            return None
        ingested = [
            m.ingested_at
            for m in repository.list_meetings_for_account(session, meeting.account_id)
            if m.ingested_at is not None
        ]
        if ingested and as_utc(max(ingested, key=as_utc)) > as_utc(record.created_at):
            return None
        return Brief.model_validate(record.content)
