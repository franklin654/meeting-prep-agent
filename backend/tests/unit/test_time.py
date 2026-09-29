from datetime import UTC, date, datetime, timedelta

import pytest

from app import config
from app.core.time import today, utcnow


def test_today_reads_demo_today_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.settings, "demo_today", date(2030, 1, 1))

    assert today() == date(2030, 1, 1)


def test_utcnow_is_tz_aware_and_close_to_real_now() -> None:
    now = utcnow()
    assert now.tzinfo is not None and now.utcoffset() == timedelta(0)
    assert abs(now - datetime.now(UTC)) < timedelta(seconds=5)


def test_today_still_reads_demo_today_not_wall_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.settings, "demo_today", date(2026, 9, 28))
    assert today() == date(2026, 9, 28)
