"""Unit tests for the Groq LLM gateway (T08).

No real network calls: the Groq SDK client is replaced with a stub that returns
canned `chat.completions.create` responses/exceptions in sequence. Covers the
three "Done when" behaviors from docs/task-breakdown.md: retry on invalid JSON,
timeout mapping, and 429 backoff-then-retry.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from groq import APITimeoutError, RateLimitError
from pydantic import BaseModel, ValidationError

from app.core.errors import LLMInvalidOutputError, LLMTimeoutError, RateLimitedError
from app.llm.client import GroqLLMClient
from tests.fakes.fake_llm import FakeLLM


class Widget(BaseModel):
    name: str
    count: int


def _completion(content: str) -> SimpleNamespace:
    """Build a stand-in for a Groq `ChatCompletion` with the given message content."""
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _rate_limit_error() -> RateLimitError:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(429, request=request)
    return RateLimitError("rate limited", response=response, body=None)


def _timeout_error() -> APITimeoutError:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return APITimeoutError(request=request)


class StubChatCompletions:
    """Stand-in for `groq.AsyncGroq().chat.completions`.

    `side_effects` is consumed in order: an `Exception` instance is raised,
    anything else is returned as the "response".
    """

    def __init__(self, side_effects: list[Any]) -> None:
        self._side_effects = list(side_effects)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self._side_effects:
            raise AssertionError("StubChatCompletions.create called more times than expected.")
        effect = self._side_effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect


class StubGroqClient:
    def __init__(self, side_effects: list[Any]) -> None:
        self.completions = StubChatCompletions(side_effects)
        self.chat = SimpleNamespace(completions=self.completions)


class FakeClock:
    """Records delays instead of actually sleeping."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)


def make_client(
    side_effects: list[Any], **kwargs: Any
) -> tuple[GroqLLMClient, StubGroqClient, FakeClock]:
    stub = StubGroqClient(side_effects)
    clock = FakeClock()
    client = GroqLLMClient(client=stub, model="test-model", sleep=clock.sleep, **kwargs)
    return client, stub, clock


# --- happy path -------------------------------------------------------------


async def test_complete_json_returns_validated_model_on_first_success() -> None:
    client, stub, _clock = make_client([_completion(json.dumps({"name": "widget", "count": 3}))])

    result = await client.complete_json("describe the widget", Widget)

    assert result == Widget(name="widget", count=3)
    assert len(stub.completions.calls) == 1
    call = stub.completions.calls[0]
    assert call["model"] == "test-model"
    assert call["response_format"] == {"type": "json_object"}
    assert call["temperature"] == 0.0


async def test_complete_json_sends_schema_and_prompt() -> None:
    client, stub, _clock = make_client([_completion(json.dumps({"name": "w", "count": 1}))])

    await client.complete_json("describe the widget", Widget, temperature=0.3, system="be terse")

    messages = stub.completions.calls[0]["messages"]
    assert messages[-1] == {"role": "user", "content": "describe the widget"}
    system_message = messages[0]["content"]
    assert "be terse" in system_message
    assert '"name"' in system_message  # schema property present
    assert stub.completions.calls[0]["temperature"] == 0.3


# --- retry on invalid JSON ---------------------------------------------------


async def test_complete_json_retries_once_on_invalid_json_then_succeeds() -> None:
    client, stub, _clock = make_client(
        [
            _completion("not json at all"),
            _completion(json.dumps({"name": "widget", "count": 3})),
        ]
    )

    result = await client.complete_json("describe the widget", Widget)

    assert result == Widget(name="widget", count=3)
    assert len(stub.completions.calls) == 2
    # The retry prompt carries the original error forward.
    retry_prompt = stub.completions.calls[1]["messages"][-1]["content"]
    assert "describe the widget" in retry_prompt
    assert "invalid" in retry_prompt.lower()


async def test_complete_json_retries_once_on_schema_validation_failure() -> None:
    client, stub, _clock = make_client(
        [
            _completion(json.dumps({"name": "widget"})),  # missing required "count"
            _completion(json.dumps({"name": "widget", "count": 3})),
        ]
    )

    result = await client.complete_json("describe the widget", Widget)

    assert result == Widget(name="widget", count=3)
    assert len(stub.completions.calls) == 2


async def test_complete_json_raises_llm_invalid_output_after_retry_fails_twice() -> None:
    client, stub, _clock = make_client(
        [
            _completion("not json"),
            _completion("still not json"),
        ]
    )

    with pytest.raises(LLMInvalidOutputError) as exc_info:
        await client.complete_json("describe the widget", Widget)

    assert exc_info.value.code == "llm_invalid_output"
    assert len(stub.completions.calls) == 2  # exactly one retry, then fail loudly


# --- timeout ------------------------------------------------------------------


async def test_complete_json_raises_llm_timeout_on_groq_timeout() -> None:
    client, stub, _clock = make_client([_timeout_error()])

    with pytest.raises(LLMTimeoutError) as exc_info:
        await client.complete_json("describe the widget", Widget)

    assert exc_info.value.code == "llm_timeout"
    assert len(stub.completions.calls) == 1  # no retry on timeout

    # The 30s timeout is passed through to the SDK call.
    assert stub.completions.calls[0]["timeout"] == 30.0


# --- 429 backoff ----------------------------------------------------------


async def test_complete_json_retries_with_backoff_on_429_then_succeeds() -> None:
    client, stub, clock = make_client(
        [
            _rate_limit_error(),
            _rate_limit_error(),
            _completion(json.dumps({"name": "widget", "count": 3})),
        ],
        max_rate_limit_retries=3,
        backoff_base_seconds=1.0,
    )

    result = await client.complete_json("describe the widget", Widget)

    assert result == Widget(name="widget", count=3)
    assert len(stub.completions.calls) == 3
    assert clock.delays == [1.0, 2.0]  # exponential backoff: base * 2**attempt


async def test_complete_json_raises_rate_limited_after_exhausting_retries() -> None:
    client, stub, clock = make_client(
        [_rate_limit_error(), _rate_limit_error(), _rate_limit_error()],
        max_rate_limit_retries=2,
        backoff_base_seconds=0.5,
    )

    with pytest.raises(RateLimitedError) as exc_info:
        await client.complete_json("describe the widget", Widget)

    assert exc_info.value.code == "rate_limited"
    assert len(stub.completions.calls) == 3  # original + 2 retries
    assert clock.delays == [0.5, 1.0]


async def test_rate_limit_retries_are_not_confused_with_json_retries() -> None:
    """A 429 that eventually succeeds should not consume the invalid-JSON retry budget."""
    client, stub, _clock = make_client(
        [
            _rate_limit_error(),
            _completion("not json"),
            _completion(json.dumps({"name": "widget", "count": 3})),
        ],
        max_rate_limit_retries=3,
    )

    result = await client.complete_json("describe the widget", Widget)

    assert result == Widget(name="widget", count=3)
    assert len(stub.completions.calls) == 3


# --- FakeLLM ------------------------------------------------------------------


async def test_fake_llm_returns_queued_response_in_order() -> None:
    fake = FakeLLM()
    fake.queue_response(Widget(name="a", count=1))
    fake.queue_response(Widget(name="b", count=2))

    first = await fake.complete_json("prompt a", Widget)
    second = await fake.complete_json("prompt b", Widget, temperature=0.3)

    assert first == Widget(name="a", count=1)
    assert second == Widget(name="b", count=2)
    assert [c.prompt for c in fake.calls] == ["prompt a", "prompt b"]
    assert fake.calls[1].temperature == 0.3


async def test_fake_llm_raises_queued_error() -> None:
    fake = FakeLLM()
    fake.queue_error(LLMInvalidOutputError("boom"))

    with pytest.raises(LLMInvalidOutputError):
        await fake.complete_json("prompt", Widget)


async def test_fake_llm_raises_assertion_error_when_no_response_queued() -> None:
    fake = FakeLLM()

    with pytest.raises(AssertionError):
        await fake.complete_json("prompt", Widget)


async def test_fake_llm_raises_assertion_error_on_schema_mismatch() -> None:
    class Other(BaseModel):
        x: int

    fake = FakeLLM()
    fake.queue_response(Other(x=1))

    with pytest.raises(AssertionError):
        await fake.complete_json("prompt", Widget)


def test_widget_validation_error_is_a_pydantic_validation_error() -> None:
    # Sanity check for the fixtures above: missing "count" really does fail validation.
    with pytest.raises(ValidationError):
        Widget.model_validate({"name": "widget"})
