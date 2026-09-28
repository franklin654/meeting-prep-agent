"""Engine and session setup for the SQLite database.

`settings.database_url` (see `app/config.py`) is the single source for the
DB location; nothing else in the app should read or construct that URL.

SQLite is dev-only here (per docs/data-model-and-schemas.md "Change rules"):
there are no migrations, just `create_db_and_tables` / `reset_db` for
`make reset-demo` (T11) to call on schema change.
"""

from __future__ import annotations

from collections.abc import Generator

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


def create_db_and_tables() -> None:
    """Create all tables that don't already exist."""
    SQLModel.metadata.create_all(engine)


def reset_db() -> None:
    """Drop and recreate every table.

    Called by the `make reset-demo` script (T11) after a schema change,
    per docs/data-model-and-schemas.md: "SQLite is dev-only: on schema
    change, run `make reset-demo` rather than writing migrations."
    """
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
