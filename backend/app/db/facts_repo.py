"""SQLite gateway for durable P1-extracted facts."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlmodel import Session, col, select

from app.core.time import utcnow
from app.db.models import ExtractedFact
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
            id=f"fact_{uuid.uuid4().hex[:8]}", account_id=account_id, meeting_id=meeting_id,
            contact_id=contact_id, kind=kind, text=text, source_quote=quote, created_at=utcnow(),
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
