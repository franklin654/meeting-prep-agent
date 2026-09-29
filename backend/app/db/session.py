"""Engine and session setup for the SQLite database.

`settings.database_url` (see `app/config.py`) is the single source for the
DB location; nothing else in the app should read or construct that URL.

SQLite is dev-only here (per docs/data-model-and-schemas.md "Change rules"):
there are no migrations, just `create_db_and_tables` / `reset_db` for
`make reset-demo` (T11) to call on schema change.
"""

from __future__ import annotations

import logging
from collections.abc import Generator

from sqlalchemy import Engine, text
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

# Imported for its side effect: registering every table on `SQLModel.metadata`
# so `create_db_and_tables`/`reset_db` see all nine tables, even if the
# caller never imports `app.db.models` directly.
from app.db import models as _models  # noqa: F401

# `check_same_thread=False` is the standard SQLModel/FastAPI setting for
# SQLite: FastAPI may use the connection from a different thread than the
# one that created it, and a single `Session` per request/call is still
# used sequentially, not concurrently.
logger = logging.getLogger(__name__)

_connect_args = {"check_same_thread": False}

engine = create_engine(settings.database_url, connect_args=_connect_args)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a `Session` bound to `engine`.

    Usage: `session: Session = Depends(get_session)` in a router, then pass
    `session` into `app.db.repository` functions — routers never touch the
    session directly (AGENTS.md hard rule 1).
    """
    with Session(engine) as session:
        yield session


BRIEF_UNIQUE_INDEX = "ux_briefrecord_meeting_mode"


def ensure_brief_unique_index(target: Engine | None = None) -> None:
    """Idempotently enforce one `briefrecord` row per (meeting_id, mode).

    `create_all` never alters an existing table, so databases created before the unique
    constraint need the index added by hand. Duplicates (if any) are removed first, keeping
    the newest `created_at`; Feedback rows pointing at a removed brief are re-pointed to the
    kept one. Counts are logged.
    """
    eng = target or engine
    with eng.begin() as conn:
        rows = conn.execute(
            text("SELECT id, meeting_id, mode, created_at FROM briefrecord ORDER BY created_at")
        ).all()
        keep: dict[tuple[str, str], str] = {}
        for row in rows:  # ascending created_at: the last one seen is the newest
            keep[(row.meeting_id, row.mode)] = row.id
        removed = 0
        for row in rows:
            kept_id = keep[(row.meeting_id, row.mode)]
            if row.id != kept_id:
                conn.execute(
                    text("UPDATE feedback SET brief_id = :kept WHERE brief_id = :old"),
                    {"kept": kept_id, "old": row.id},
                )
                conn.execute(text("DELETE FROM briefrecord WHERE id = :old"), {"old": row.id})
                removed += 1
        conn.execute(
            text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {BRIEF_UNIQUE_INDEX} "
                "ON briefrecord (meeting_id, mode)"
            )
        )
    logger.info("db.brief_unique_index rows=%d duplicates_removed=%d", len(rows), removed)


def create_db_and_tables(target: Engine | None = None) -> None:
    """Create all tables that don't already exist, plus the brief unique index."""
    SQLModel.metadata.create_all(target or engine)
    ensure_brief_unique_index(target)


def reset_db() -> None:
    """Drop and recreate every table.

    Called by the `make reset-demo` script (T11) after a schema change,
    per docs/data-model-and-schemas.md: "SQLite is dev-only: on schema
    change, run `make reset-demo` rather than writing migrations."
    """
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
