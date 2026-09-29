"""SQLite gateway for transient capture drafts and prepared meeting markers."""

from __future__ import annotations

import uuid
from typing import Any

from sqlmodel import Session

from app.core.errors import NotFoundError
from app.core.time import utcnow
from app.db.models import CaptureDraft, MeetingPrepared


def create_draft(
    session: Session,
    *,
    meeting_id: str,
    transcript: str,
    extraction: dict[str, Any],
    items: list[dict[str, Any]],
) -> CaptureDraft:
    draft = CaptureDraft(
        id=f"draft_{uuid.uuid4().hex[:8]}", meeting_id=meeting_id, transcript=transcript,
        extraction=extraction, items=items, created_at=utcnow(),
    )
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return draft


def get_draft(session: Session, draft_id: str) -> CaptureDraft | None:
    return session.get(CaptureDraft, draft_id)


def set_draft_status(session: Session, draft_id: str, status: str) -> CaptureDraft:
    draft = get_draft(session, draft_id)
    if draft is None:
        raise NotFoundError(f"Capture draft {draft_id!r} not found.")
    draft.status = status
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return draft


def mark_prepared(session: Session, meeting_id: str) -> MeetingPrepared:
    existing = session.get(MeetingPrepared, meeting_id)
    if existing is not None:
        return existing
    row = MeetingPrepared(meeting_id=meeting_id, prepared_at=utcnow())
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def unmark_prepared(session: Session, meeting_id: str) -> None:
    row = session.get(MeetingPrepared, meeting_id)
    if row is not None:
        session.delete(row)
        session.commit()


def is_prepared(session: Session, meeting_id: str) -> bool:
    return session.get(MeetingPrepared, meeting_id) is not None
