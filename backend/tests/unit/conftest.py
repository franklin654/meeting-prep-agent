"""Shared fixtures for `app.db` tests.

Each test gets its own temp-file SQLite database (not mocked, not the
module-level `app.db.session.engine`) so tests can run in parallel and
never touch a real `app.db` file on disk outside the temp dir.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine

# Import for the side effect of registering all nine tables on
# `SQLModel.metadata` before `create_all` runs.
from app.db import models as _models  # noqa: F401


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session
    engine.dispose()
