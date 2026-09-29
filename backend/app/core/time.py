"""Time utilities.

AGENTS.md hard rule 6: business logic reads "today" from `settings.demo_today`,
never `date.today()` / `datetime.now()`. Every module that needs "today" should
call `today()` here rather than reading `settings.demo_today` directly, so there
is exactly one place that rule could be broken.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.config import settings


def today() -> date:
    """Return the demo "today" for business logic."""
    return settings.demo_today


def utcnow() -> datetime:
    """Wall clock (tz-aware UTC) for record-keeping timestamps only.

    Use for `ingested_at`, job `created_at`/`finished_at` and brief `created_at`. Business
    logic such as overdue still uses `today()` / `settings.demo_today` (AGENTS.md hard rule 6).
    """
    return datetime.now(UTC)
