from datetime import date
from pathlib import Path

import pytest

from app.config import _REPO_ROOT_ENV, Settings


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


def test_env_file_resolves_to_repo_root_regardless_of_cwd() -> None:
    """The computed env_file path must point at <repo root>/.env, independent of
    os.getcwd() at import/instantiation time (see AGENTS.md hard rule and the
    config.py bug this guards against)."""
    repo_root = Path(__file__).resolve().parents[3]  # backend/tests/unit/.. -> repo root
    assert _REPO_ROOT_ENV == repo_root / ".env"


def test_settings_load_real_values_from_env_file_at_repo_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A `.env` file at the location config.py resolves should be picked up by
    Settings, even when the process cwd is somewhere else entirely."""
    fake_env = tmp_path / "fake_repo_root" / ".env"
    fake_env.parent.mkdir(parents=True)
    fake_env.write_text("DEMO_USER_ID=not-a-secret-placeholder\n", encoding="utf-8")

    # Point Settings at our fake env file rather than the real repo root, and prove
    # cwd doesn't matter by running from an unrelated temp directory.
    other_cwd = tmp_path / "somewhere_else"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)
    monkeypatch.delenv("DEMO_USER_ID", raising=False)

    settings = Settings(_env_file=fake_env)  # type: ignore[call-arg]

    assert settings.demo_user_id == "not-a-secret-placeholder"


def test_settings_work_with_defaults_when_env_file_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A missing env_file (e.g. CI, fresh clone) must not raise; pydantic-settings
    silently skips it and Settings falls back to OS env / field defaults."""
    missing_env = tmp_path / "does_not_exist" / ".env"
    assert not missing_env.exists()

    monkeypatch.delenv("DEMO_TODAY", raising=False)
    monkeypatch.delenv("DEMO_USER_ID", raising=False)

    settings = Settings(_env_file=missing_env)  # type: ignore[call-arg]

    assert settings.demo_today == date(2026, 9, 28)
    assert settings.demo_user_id == "priya"


def test_module_level_settings_instance_does_not_raise_without_root_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanity check that the default `_REPO_ROOT_ENV` (used by the real `settings`
    singleton) not existing is a normal, silently-handled case, not an error."""
    if _REPO_ROOT_ENV.exists():
        pytest.skip("root .env is present in this checkout; nothing to assert here")

    # Instantiating with the real default env_file should not raise even though
    # the file doesn't exist in this environment (e.g. CI, or this worktree).
    Settings()
