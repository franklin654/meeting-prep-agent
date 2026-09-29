"""Startup validation (T08c): the lifespan hook fails fast on bad LLM config.

Only `with TestClient(app)` runs the lifespan; plain `TestClient(app)` (used by
other tests) does not, so no-key unit tests and CI are unaffected.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import create_engine

import app.db.session as db_session
import app.main as main_module
from app.config import ConfigError, Settings

SENTINEL = "sk-test-SENTINEL"


@pytest.fixture(autouse=True)
def _tmp_engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """The lifespan creates tables; keep it off the default ./app.db."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'startup.db'}", connect_args={"check_same_thread": False}
    )
    monkeypatch.setattr(db_session, "engine", engine)
    yield
    engine.dispose()


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "llm_provider": "openai",
        "llm_model": "gpt-test",
        "openai_api_key": SENTINEL,
        "hindsight_llm_provider": "groq",
        "hindsight_llm_model": "hs-model",
        "hindsight_llm_api_key": SENTINEL,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _start(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> None:
    monkeypatch.setattr(main_module, "settings", _settings(**overrides))
    with TestClient(main_module.app):
        pass


def test_valid_config_starts_and_serves_health(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "settings", _settings())
    with TestClient(main_module.app) as client:
        assert client.get("/api/health").json() == {"status": "ok"}


def test_unknown_app_provider_names_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigError, match="LLM_PROVIDER") as exc:
        _start(monkeypatch, llm_provider="bogus")
    assert SENTINEL not in str(exc.value)


def test_missing_app_key_names_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigError, match="OPENAI_API_KEY") as exc:
        _start(monkeypatch, openai_api_key=None)
    assert SENTINEL not in str(exc.value)


@pytest.mark.parametrize(
    ("override", "variable"),
    [
        ({"hindsight_llm_provider": "bogus"}, "HINDSIGHT_LLM_PROVIDER"),
        ({"hindsight_llm_model": None}, "HINDSIGHT_LLM_MODEL"),
        ({"hindsight_llm_api_key": None}, "HINDSIGHT_LLM_API_KEY"),
    ],
)
def test_bad_hindsight_config_names_variable(
    monkeypatch: pytest.MonkeyPatch, override: dict[str, Any], variable: str
) -> None:
    with pytest.raises(ConfigError, match=variable) as exc:
        _start(monkeypatch, **override)
    assert SENTINEL not in str(exc.value)
