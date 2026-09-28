"""complete_text on Groq and FakeLLM, plus the provider factory (T08b). No network."""

from __future__ import annotations

import importlib

import pytest

from app.config import ConfigError, Settings
from app.core.errors import LLMTimeoutError
from app.llm.client import get_llm_client
from tests.fakes.fake_llm import FakeLLM
from tests.unit.test_llm_client import (
    _completion,
    _rate_limit_error,
    _timeout_error,
    make_client,
)

# --- complete_text (Groq) -----------------------------------------------------


async def test_complete_text_returns_plain_string_without_json_mode() -> None:
    client, stub, _clock = make_client([_completion("hello there")])

    result = await client.complete_text("say hi", temperature=0.3, system="be terse")

    assert result == "hello there"
    call = stub.completions.calls[0]
    assert "response_format" not in call
    assert call["temperature"] == 0.3
    assert call["messages"][0] == {"role": "system", "content": "be terse"}
    assert call["messages"][-1] == {"role": "user", "content": "say hi"}


async def test_complete_text_backs_off_on_429_and_maps_timeout() -> None:
    client, _stub, clock = make_client(
        [_rate_limit_error(), _completion("ok")], backoff_base_seconds=1.0
    )
    assert await client.complete_text("x") == "ok"
    assert clock.delays == [1.0]

    client, _stub, _clock = make_client([_timeout_error()])
    with pytest.raises(LLMTimeoutError):
        await client.complete_text("x")


# --- FakeLLM.complete_text ------------------------------------------------------


async def test_fake_llm_complete_text_returns_queued_text_and_records_call() -> None:
    fake = FakeLLM()
    fake.queue_text("first")
    fake.queue_text_error(LLMTimeoutError("slow"))

    assert await fake.complete_text("p1", temperature=0.3, system="s") == "first"
    assert fake.text_calls[0].prompt == "p1"
    assert fake.text_calls[0].temperature == 0.3
    assert fake.text_calls[0].system == "s"
    with pytest.raises(LLMTimeoutError):
        await fake.complete_text("p2")
    with pytest.raises(AssertionError):
        await fake.complete_text("p3")


# --- factory -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("provider", "cls"),
    [("groq", "GroqProvider"), ("openai", "OpenAIProvider"), ("anthropic", "AnthropicProvider")],
)
def test_factory_picks_adapter_from_settings(
    monkeypatch: pytest.MonkeyPatch, provider: str, cls: str
) -> None:
    for name in ("OPENAI_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", provider)
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv(f"{provider.upper()}_API_KEY", "not-a-real-key")

    client = get_llm_client(Settings(_env_file=None))  # type: ignore[call-arg]

    module = importlib.import_module(f"app.llm.providers.{provider}")
    assert type(client) is getattr(module, cls)


def test_factory_fails_fast_on_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("OPENAI_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")

    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        get_llm_client(Settings(_env_file=None))  # type: ignore[call-arg]
