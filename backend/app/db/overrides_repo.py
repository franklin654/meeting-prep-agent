"""SQLite gateway for app-layer memory visibility and corrections."""

from __future__ import annotations

import uuid

from sqlmodel import Session, col, select

from app.core.time import utcnow
from app.db.models import MemoryOverride


def create_override(
    session: Session, *, target_type: str, target_id: str, action: str, corrected_text: str | None
) -> MemoryOverride:
    row = MemoryOverride(
        id=f"ovr_{uuid.uuid4().hex[:8]}", target_type=target_type, target_id=target_id,
        action=action, corrected_text=corrected_text, created_at=utcnow(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_overrides(session: Session, *, target_type: str | None = None) -> list[MemoryOverride]:
    statement = select(MemoryOverride).order_by(
        col(MemoryOverride.created_at), col(MemoryOverride.id)
    )
    if target_type is not None:
        statement = statement.where(MemoryOverride.target_type == target_type)
    return list(session.exec(statement))


def delete_overrides(
    session: Session, *, target_id: str, target_type: str | None = None
) -> int:
    statement = select(MemoryOverride).where(MemoryOverride.target_id == target_id)
    if target_type is not None:
        statement = statement.where(MemoryOverride.target_type == target_type)
    rows = list(session.exec(statement))
    for row in rows:
        session.delete(row)
    session.commit()
    return len(rows)
