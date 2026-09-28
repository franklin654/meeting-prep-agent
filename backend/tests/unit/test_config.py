from datetime import date

import pytest

from app.config import Settings


def test_demo_today_reads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_TODAY", "2026-08-01")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.demo_today == date(2026, 8, 1)


def test_demo_today_has_a_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEMO_TODAY", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.demo_today == date(2026, 9, 28)


def test_settings_ignore_unknown_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOME_FUTURE_TICKETS_VAR", "whatever")

    # Should not raise even though extra="ignore" allows unrelated env vars.
    Settings(_env_file=None)  # type: ignore[call-arg]
