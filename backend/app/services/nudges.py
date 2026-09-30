"""Fast, deterministic dashboard nudges built only from SQLite read models."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date

from sqlmodel import Session

from app.core.time import today
from app.db import meetings_repo, repository
from app.db.meetings_repo import MeetingRow
from app.db.models import Account, Commitment, Contact
from app.schemas.api import Nudge
from app.schemas.enums import Owner


def _commitment_label(text: str) -> str:
    cleaned = re.sub(
        r"^(?:our\s+|(?:send|share|deliver|provide)\s+(?:(?:the|a|an)\s+)?)",
        "",
        text.strip(),
        flags=re.IGNORECASE,
    )
    return cleaned[:1].upper() + cleaned[1:]


def _overdue_nudges(
    session: Session,
    accounts: dict[str, Account],
    upcoming: Sequence[MeetingRow],
) -> list[Nudge]:
    earliest_meeting: dict[str, str] = {}
    for row in upcoming:
        earliest_meeting.setdefault(row.meeting.account_id, row.meeting.id)

    rows: list[tuple[Commitment, str]] = []
    for commitment in repository.list_overdue_commitments(session):
        account = accounts.get(commitment.account_id)
        if (
            commitment.owner is Owner.us
            and account is not None
            and account.stage not in {"closed_won", "closed_lost"}
            and commitment.due_date is not None
        ):
            rows.append((commitment, account.name))
    rows.sort(key=lambda pair: (pair[0].due_date, pair[0].id))
    # Brief enrichment is deliberately read-time only and may not be persisted.
    # Match _enriched_commitments: the oldest overdue AE commitment per account
    # is the single critical item; later overdue rows remain amber.
    # Rows are globally due-date sorted; choose one oldest row per account.
    seen_accounts: set[str] = set()
    critical_ids: set[str] = set()
    for commitment, _account_name in rows:
        if commitment.account_id not in seen_accounts:
            critical_ids.add(commitment.id)
            seen_accounts.add(commitment.account_id)

    output: list[Nudge] = []
    for commitment, account_name in rows[:3]:
        assert commitment.due_date is not None
        days = (today() - commitment.due_date).days
        output.append(
            Nudge(
                kind="overdue_commitment",
                text=(
                    f"{_commitment_label(commitment.text)} is {days} days overdue ({account_name})"
                ),
                link=f"/meetings/{earliest_meeting[commitment.account_id]}"
                if commitment.account_id in earliest_meeting
                else "/",
                critical=commitment.id in critical_ids,
            )
        )
    return output


def _brief_ready_nudges(upcoming: Sequence[MeetingRow]) -> list[Nudge]:
    return [
        Nudge(
            kind="brief_ready",
            text=(
                f"Brief ready: {row.meeting.title} - {row.account_name}, "
                f"{row.meeting.scheduled_at:%b} {row.meeting.scheduled_at.day}"
            ),
            link=f"/meetings/{row.meeting.id}",
        )
        for row in upcoming
        if row.brief_ready
    ]


def _they_owe_nudges(
    session: Session,
    accounts: dict[str, Account],
    upcoming: Sequence[MeetingRow],
) -> list[Nudge]:
    earliest_meeting: dict[str, str] = {}
    for row in upcoming:
        earliest_meeting.setdefault(row.meeting.account_id, row.meeting.id)
    rows = [
        commitment
        for commitment in repository.list_overdue_commitments(session)
        if commitment.owner is Owner.them
        and (account := accounts.get(commitment.account_id)) is not None
        and account.stage not in {"closed_won", "closed_lost"}
    ]
    rows.sort(key=lambda commitment: (commitment.due_date or date.max, commitment.id))
    return [
        Nudge(
            kind="they_owe_overdue",
            text=f"Waiting on {_commitment_label(commitment.text)} ({account.name})",
            link=f"/meetings/{earliest_meeting[commitment.account_id]}"
            if commitment.account_id in earliest_meeting
            else "/",
        )
        for commitment in rows[:3]
        if (account := accounts.get(commitment.account_id)) is not None
    ]


def _no_history_nudges(
    done: Sequence[MeetingRow],
    upcoming: Sequence[MeetingRow],
    accounts: dict[str, Account],
) -> list[Nudge]:
    output: list[Nudge] = []
    seen_accounts: set[str] = set()
    for row in upcoming:
        account_id = row.meeting.account_id
        account = accounts.get(account_id)
        if (
            account is None
            or account.stage in {"closed_won", "closed_lost"}
            or any(previous.meeting.account_id == account_id for previous in done)
            or account_id in seen_accounts
        ):
            continue
        seen_accounts.add(account_id)
        output.append(
            Nudge(
                kind="no_history",
                text=f"No history yet: {row.account_name}'s first meeting is coming up",
                link=f"/meetings/{row.meeting.id}",
            )
        )
    return output


def _silent_contact_nudges(
    done: Sequence[MeetingRow], upcoming: Sequence[MeetingRow], accounts: dict[str, Account]
) -> list[Nudge]:
    today_date = today()
    upcoming_contact_ids = {
        contact.id
        for row in upcoming
        for contact in row.attendees
        if contact.account_id is not None
    }
    last_call: dict[str, tuple[Contact, str, date]] = {}
    for row in done:
        account = accounts.get(row.meeting.account_id)
        if account is None or account.stage in {"closed_won", "closed_lost"}:
            continue
        meeting_day = row.meeting.scheduled_at.date()
        for contact in row.attendees:
            if contact.account_id is None:
                continue
            previous = last_call.get(contact.id)
            if previous is None or meeting_day > previous[2]:
                last_call[contact.id] = (contact, row.account_name, meeting_day)

    silent: list[tuple[int, Contact, str]] = []
    for contact_id, (contact, account_name, last_date) in last_call.items():
        if contact_id in upcoming_contact_ids:
            continue
        days = (today_date - last_date).days
        if days > 21:
            silent.append((days, contact, account_name))
    silent.sort(key=lambda row: (-row[0], row[1].name.casefold(), row[1].id))
    return [
        Nudge(
            kind="silent_contact",
            text=(
                f"{contact.name} ({contact.role}, {account_name}) hasn't been on a call "
                f"for {days} days"
                if contact.role
                else f"{contact.name} ({account_name}) hasn't been on a call for {days} days"
            ),
            link=f"/contacts/{contact.id}",
        )
        for days, contact, account_name in silent[:2]
    ]


def build_nudges(session: Session) -> list[Nudge]:
    """Return nudge rows in priority order; this function makes no external calls."""
    rows = meetings_repo.list_meeting_rows(session)
    upcoming = [row for row in rows if row.meeting.status == "upcoming"]
    done = [row for row in rows if row.meeting.status == "done"]
    accounts = {account.id: account for account in repository.list_accounts(session)}
    nudges = _overdue_nudges(session, accounts, upcoming)
    nudges.extend(_they_owe_nudges(session, accounts, upcoming))
    nudges.extend(_no_history_nudges(done, upcoming, accounts))
    nudges.extend(_brief_ready_nudges(upcoming))
    nudges.extend(_silent_contact_nudges(done, upcoming, accounts))
    return nudges[:8]
