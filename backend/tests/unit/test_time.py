from datetime import date

import pytest

from app import config
from app.core.time import today


def test_today_reads_demo_today_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.settings, "demo_today", date(2030, 1, 1))

    assert today() == date(2030, 1, 1)
