"""SQLite gateway for durable P1-extracted facts."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlmodel import Session, col, select

from app.core.time import utcnow
from app.db.models import Account, ExtractedFact, Meeting
from app.schemas.enums import FactKind


def replace_meeting_facts(
    session: Session,
    meeting_id: str,
    account_id: str,
    rows: Sequence[tuple[str | None, FactKind, str, str]],
) -> list[ExtractedFact]:
    for fact in session.exec(select(ExtractedFact).where(ExtractedFact.meeting_id == meeting_id)):
        session.delete(fact)
    created = [
        ExtractedFact(
            id=f"fact_{uuid.uuid4().hex[:8]}",
            account_id=account_id,
            meeting_id=meeting_id,
            contact_id=contact_id,
            kind=kind,
            text=text,
            source_quote=quote,
            created_at=utcnow(),
        )
        for contact_id, kind, text, quote in rows
    ]
    session.add_all(created)
    session.commit()
    for fact in created:
        session.refresh(fact)
    return created


def list_account_facts(session: Session, account_id: str) -> list[ExtractedFact]:
    return list(
        session.exec(
            select(ExtractedFact)
            .where(ExtractedFact.account_id == account_id)
            .order_by(col(ExtractedFact.created_at), col(ExtractedFact.id))
        )
    )


def get_fact(session: Session, fact_id: str) -> ExtractedFact | None:
    return session.get(ExtractedFact, fact_id)


def list_backfill_candidates(
    session: Session, *, limit: int | None = None
) -> list[tuple[Meeting, Account]]:
    statement = (
        select(Meeting, Account)
        .join(Account, col(Account.id) == col(Meeting.account_id))
        .where(Meeting.status == "done", col(Meeting.transcript).is_not(None))
        .where(~select(ExtractedFact.id).where(ExtractedFact.meeting_id == Meeting.id).exists())
        .order_by(col(Meeting.scheduled_at), col(Meeting.id))
    )
    if limit is not None:
        statement = statement.limit(limit)
    return list(session.exec(statement).all())
