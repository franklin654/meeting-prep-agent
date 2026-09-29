"""SQLite reads and writes for feedback (T19).

Separate from `repository.py` (which stays untouched); it reuses that module's
`get_brief_record` and `create_feedback`. Functions take a `session_factory`
(or a session for the plain list) and return plain loaded objects.
"""

from __future__ import annotations

import uuid

from sqlmodel import Session, select

from app.core.errors import NotFoundError
from app.core.time import utcnow
from app.db import repository
from app.db.brief_repo import SessionFactory
from app.db.models import Feedback
from app.schemas.brief import SectionKey


def list_all_feedback(session: Session) -> list[Feedback]:
    """Every feedback row, oldest first (the style profile is global)."""
    statement = select(Feedback).order_by(Feedback.created_at, Feedback.id)  # type: ignore[arg-type]
    return list(session.exec(statement).all())


def load_all_feedback(session_factory: SessionFactory) -> list[Feedback]:
    with session_factory() as session:
        return list_all_feedback(session)


def store_feedback(
    session_factory: SessionFactory, brief_id: str, section: SectionKey, action: str
) -> Feedback:
    """Store one feedback row for an existing brief record; NotFoundError otherwise."""
    with session_factory() as session:
        if repository.get_brief_record(session, brief_id) is None:
            raise NotFoundError(f"Brief {brief_id!r} not found.")
        return repository.create_feedback(
            session,
            Feedback(
                id=f"fb_{uuid.uuid4().hex[:8]}",
                brief_id=brief_id,
                section=section,
                action=action,
                created_at=utcnow(),
            ),
        )
