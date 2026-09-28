"""LLM provider selection and fail-fast config validation (T08b).

Errors must name the environment variable and never contain its value.
"""

from __future__ import annotations

import pytest

from app.config import ConfigError, Settings

_LLM_ENV_VARS = (
    "LLM_PROVIDER",
    "LLM_MODEL",
    "OPENAI_API_KEY",
    "GROQ_API_KEY",
    "ANTHROPIC_API_KEY",
    "HINDSIGHT_LLM_PROVIDER",
    "HINDSIGHT_LLM_MODEL",
    "HINDSIGHT_LLM_API_KEY",
)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in _LLM_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _valid_env(mp: pytest.MonkeyPatch, provider: str = "groq") -> None:
    mp.setenv("LLM_PROVIDER", provider)
    mp.setenv("LLM_MODEL", "some-model")
    mp.setenv(f"{provider.upper()}_API_KEY", "app-secret-value")
    mp.setenv("HINDSIGHT_LLM_PROVIDER", "openai")
    mp.setenv("HINDSIGHT_LLM_MODEL", "hs-model")
    mp.setenv("HINDSIGHT_LLM_API_KEY", "hs-secret-value")


def _settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.parametrize("provider", ["openai", "groq", "anthropic"])
def test_valid_config_passes_for_each_provider(env: pytest.MonkeyPatch, provider: str) -> None:
    _valid_env(env, provider)

    settings = _settings()
    settings.validate_llm_config()

    assert settings.llm_provider == provider
    assert settings.app_llm_api_key == "app-secret-value"
    assert settings.hindsight_llm_provider == "openai"


def test_unknown_app_provider_fails_naming_the_variable(env: pytest.MonkeyPatch) -> None:
    _valid_env(env)
    env.setenv("LLM_PROVIDER", "gemini")

    with pytest.raises(ConfigError, match="LLM_PROVIDER"):
        _settings().validate_llm_config()


def test_unknown_hindsight_provider_fails_naming_the_variable(env: pytest.MonkeyPatch) -> None:
    _valid_env(env)
    env.setenv("HINDSIGHT_LLM_PROVIDER", "ollama")

    with pytest.raises(ConfigError, match="HINDSIGHT_LLM_PROVIDER"):
        _settings().validate_llm_config()


@pytest.mark.parametrize(
    ("provider", "variable"),
    [("openai", "OPENAI_API_KEY"), ("groq", "GROQ_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY")],
)
def test_missing_key_for_selected_app_provider_names_the_variable(
    env: pytest.MonkeyPatch, provider: str, variable: str
) -> None:
    _valid_env(env, provider)
    env.delenv(variable)

    with pytest.raises(ConfigError, match=variable):
        _settings().validate_llm_config()


def test_key_of_a_non_selected_provider_is_not_required(env: pytest.MonkeyPatch) -> None:
    _valid_env(env, "groq")  # only GROQ_API_KEY set
    _settings().validate_llm_config()


def test_missing_hindsight_key_or_model_fails(env: pytest.MonkeyPatch) -> None:
    _valid_env(env)
    env.delenv("HINDSIGHT_LLM_API_KEY")
    with pytest.raises(ConfigError, match="HINDSIGHT_LLM_API_KEY"):
        _settings().validate_llm_config()

    env.setenv("HINDSIGHT_LLM_API_KEY", "hs-secret-value")
    env.delenv("HINDSIGHT_LLM_MODEL")
    with pytest.raises(ConfigError, match="HINDSIGHT_LLM_MODEL"):
        _settings().validate_llm_config()


def test_config_errors_never_contain_key_values(env: pytest.MonkeyPatch) -> None:
    _valid_env(env)
    env.setenv("LLM_PROVIDER", "nope")
    with pytest.raises(ConfigError) as exc_info:
        _settings().validate_llm_config()
    assert "secret-value" not in str(exc_info.value)

    env.setenv("LLM_PROVIDER", "openai")  # OPENAI_API_KEY unset; GROQ key is set
    with pytest.raises(ConfigError) as exc_info:
        _settings().validate_llm_config()
    assert "secret-value" not in str(exc_info.value)


def test_legacy_llm_api_key_is_gone() -> None:
    assert "llm_api_key" not in Settings.model_fields
