"""SQLite persistence: SQLModel tables, engine/session setup and the repository gateway.

Per AGENTS.md hard rule 1, only `app.db.repository` touches DB sessions for
reads/writes; other modules go through the functions in `repository.py`
rather than importing `session.py` or `models.py` directly (routers/services
get a `Session` from `session.get_session` as a FastAPI dependency and pass
it into repository functions).
"""

from __future__ import annotations
