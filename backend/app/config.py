"""App configuration, loaded from environment variables (and `.env` if present).

Business logic must read "today" from `settings.demo_today`, never
`date.today()` / `datetime.now()` — see AGENTS.md hard rule 6.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# The repo's single `.env` lives at the repo root (also read by docker-compose.yml
# for its own ${VAR} substitution — there is deliberately no backend/.env). Resolve
# it relative to this file's own location, not the process's cwd, so settings load
# correctly whether the process is started from the repo root, backend/, or elsewhere.
# backend/app/config.py -> .parent = backend/app, .parent.parent = backend,
# .parent.parent.parent = repo root.
_REPO_ROOT_ENV = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT_ENV, env_file_encoding="utf-8", extra="ignore"
    )

    # Demo clock. See docs/technical-design.md ("Config, local dev and deployment").
    demo_today: date = date(2026, 9, 28)
    demo_user_id: str = "priya"

    # Placeholders for env vars named in docs/technical-design.md; the modules that
    # actually use them (db, memory, llm) are built in later tickets (T02, T06-T08).
    database_url: str = "sqlite:///./app.db"
    hindsight_url: str = "http://localhost:8888"
    llm_provider: str = "groq"
    llm_model: str = "llama-3.1-8b-instant"
    llm_api_key: str | None = None


settings = Settings()
