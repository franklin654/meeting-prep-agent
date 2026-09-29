"""OpenAI and Anthropic adapter tests with mocked HTTP (T08b). No network.

The real provider SDKs run against an `httpx.MockTransport`, so request shape
(structured outputs / forced tool call), response parsing, and SDK error mapping
(timeout, 429) are exercised without touching the internet.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import anthropic
import httpx
import httpx2
import openai
import pytest
from pydantic import BaseModel

from app.core.errors import LLMInvalidOutputError, LLMTimeoutError, RateLimitedError
from app.llm.providers.anthropic import AnthropicProvider
from app.llm.providers.openai import OpenAIProvider


class Widget(BaseModel):
    name: str
    count: int


class Script:
    """Feeds queued responses/exceptions to a MockTransport and records requests."""

    def __init__(self, effects: list[Any], lib: Any = httpx) -> None:
        self.effects = list(effects)
        self.lib = lib  # the anthropic SDK uses `httpx2`; openai uses `httpx`
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: Any) -> Any:
        self.requests.append(json.loads(request.content))
        if not self.effects:
            raise AssertionError("more HTTP calls than scripted")
        effect = self.effects.pop(0)
        if effect is TIMEOUT:
            raise self.lib.ReadTimeout("too slow", request=request)
        status, body = effect
        return self.lib.Response(status, json=body)

    def http_client(self) -> Any:
        return self.lib.AsyncClient(transport=self.lib.MockTransport(self))


class Clock:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)


# --- response builders ---------------------------------------------------------


def oa_ok(content: str) -> tuple[int, dict[str, Any]]:
    return 200, {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    }


def an_message(blocks: list[dict[str, Any]]) -> tuple[int, dict[str, Any]]:
    return 200, {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "test-model",
        "content": blocks,
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def an_tool(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    return an_message(
        [{"type": "tool_use", "id": "toolu_1", "name": "respond", "input": payload}]
    )


def an_text(text: str) -> tuple[int, dict[str, Any]]:
    return an_message([{"type": "text", "text": text}])


TIMEOUT = object()
RATE_LIMITED = (429, {"error": {"message": "slow down", "type": "rate_limit_error"}})
GOOD = {"name": "widget", "count": 3}


def make_openai(effects: list[Any], **kw: Any) -> tuple[OpenAIProvider, Script, Clock]:
    script, clock = Script(effects), Clock()
    sdk = openai.AsyncOpenAI(
        api_key="not-a-real-key", http_client=script.http_client(), max_retries=0
    )
    return OpenAIProvider(client=sdk, model="test-model", sleep=clock.sleep, **kw), script, clock


def make_anthropic(effects: list[Any], **kw: Any) -> tuple[AnthropicProvider, Script, Clock]:
    script, clock = Script(effects, httpx2), Clock()
    sdk = anthropic.AsyncAnthropic(
        api_key="not-a-real-key", http_client=script.http_client(), max_retries=0
    )
    return AnthropicProvider(client=sdk, model="test-model", sleep=clock.sleep, **kw), script, clock


Maker = Callable[..., tuple[Any, Script, Clock]]
PROVIDERS = pytest.mark.parametrize(
    ("maker", "ok_json", "ok_text", "bad"),
    [
        (make_openai, lambda p: oa_ok(json.dumps(p)), oa_ok, oa_ok("not json")),
        (make_anthropic, an_tool, an_text, an_tool({"name": "widget"})),
    ],
    ids=["openai", "anthropic"],
)


# --- shared behavior, both adapters -----------------------------------------------


@PROVIDERS
async def test_complete_json_returns_validated_model(
    maker: Maker, ok_json: Any, ok_text: Any, bad: Any
) -> None:
    client, script, _ = maker([ok_json(GOOD)])

    assert await client.complete_json("describe", Widget, temperature=0.3) == Widget(
        name="widget", count=3
    )
    assert script.requests[0]["model"] == "test-model"
    if "temperature" in script.requests[0] or maker is make_openai:
        assert script.requests[0]["temperature"] == 0.3


@PROVIDERS
async def test_invalid_output_retries_once_then_succeeds(
    maker: Maker, ok_json: Any, ok_text: Any, bad: Any
) -> None:
    client, script, _ = maker([bad, ok_json(GOOD)])

    assert await client.complete_json("describe", Widget) == Widget(name="widget", count=3)
    assert len(script.requests) == 2


@PROVIDERS
async def test_invalid_output_twice_raises(
    maker: Maker, ok_json: Any, ok_text: Any, bad: Any
) -> None:
    client, script, _ = maker([bad, bad])

    with pytest.raises(LLMInvalidOutputError):
        await client.complete_json("describe", Widget)
    assert len(script.requests) == 2


@PROVIDERS
async def test_429_backs_off_then_succeeds_and_then_gives_up(
    maker: Maker, ok_json: Any, ok_text: Any, bad: Any
) -> None:
    client, script, clock = maker(
        [RATE_LIMITED, RATE_LIMITED, ok_json(GOOD)], backoff_base_seconds=1.0
    )
    assert await client.complete_json("describe", Widget) == Widget(name="widget", count=3)
    assert clock.delays == [1.0, 2.0]

    client, script, clock = maker(
        [RATE_LIMITED, RATE_LIMITED, RATE_LIMITED],
        max_rate_limit_retries=2,
        backoff_base_seconds=0.5,
    )
    with pytest.raises(RateLimitedError):
        await client.complete_json("describe", Widget)
    assert len(script.requests) == 3
    assert clock.delays == [0.5, 1.0]


@PROVIDERS
async def test_timeout_maps_to_llm_timeout_without_retry(
    maker: Maker, ok_json: Any, ok_text: Any, bad: Any
) -> None:
    client, script, _ = maker([TIMEOUT])

    with pytest.raises(LLMTimeoutError):
        await client.complete_json("describe", Widget)
    assert len(script.requests) == 1


@PROVIDERS
async def test_complete_text_returns_plain_text(
    maker: Maker, ok_json: Any, ok_text: Any, bad: Any
) -> None:
    client, script, _ = maker([ok_text("just words")])

    assert await client.complete_text("say", temperature=0.3, system="be terse") == "just words"
    body = script.requests[0]
    if maker is make_openai:
        assert body["temperature"] == 0.3
    assert "be terse" in json.dumps(body)
    assert "response_format" not in body
    assert "tools" not in body


@PROVIDERS
async def test_logs_usage_without_prompt_or_completion_text(
    maker: Maker, ok_json: Any, ok_text: Any, bad: Any, caplog: pytest.LogCaptureFixture
) -> None:
    client, _, _ = maker([ok_json(GOOD)])

    with caplog.at_level("INFO"):
        await client.complete_json("secret prompt text", Widget)

    messages = [
        record.getMessage() for record in caplog.records if "llm.usage" in record.getMessage()
    ]
    assert len(messages) == 1
    assert "call_type=json" in messages[0]
    assert "model=test-model" in messages[0]
    assert "prompt_tokens=" in messages[0]
    assert "completion_tokens=" in messages[0]
    assert "secret prompt text" not in messages[0]


@PROVIDERS
async def test_complete_text_backs_off_on_429_and_maps_timeout(
    maker: Maker, ok_json: Any, ok_text: Any, bad: Any
) -> None:
    client, _, clock = maker([RATE_LIMITED, ok_text("fine")], backoff_base_seconds=1.0)
    assert await client.complete_text("say") == "fine"
    assert clock.delays == [1.0]

    client, _, _ = maker([TIMEOUT])
    with pytest.raises(LLMTimeoutError):
        await client.complete_text("say")


# --- request shape, per provider -----------------------------------------------------


async def test_openai_sends_json_schema_structured_output() -> None:
    client, script, _ = make_openai([oa_ok(json.dumps(GOOD))])

    await client.complete_json("describe", Widget, system="be terse")

    body = script.requests[0]
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["name"] == "Widget"
    assert fmt["json_schema"]["schema"] == Widget.model_json_schema()
    assert body["messages"][-1] == {"role": "user", "content": "describe"}
    assert "be terse" in body["messages"][0]["content"]


async def test_anthropic_forces_a_tool_call_with_pydantic_schema() -> None:
    client, script, _ = make_anthropic([an_tool(GOOD)])

    await client.complete_json("describe", Widget, system="be terse")

    body = script.requests[0]
    assert len(body["tools"]) == 1
    tool = body["tools"][0]
    assert tool["input_schema"] == Widget.model_json_schema()
    assert body["tool_choice"] == {"type": "tool", "name": tool["name"]}
    assert body["system"] == "be terse"
    assert body["messages"][-1]["role"] == "user"
    assert body["max_tokens"] > 0
    assert "temperature" not in body  # the installed SDK exposes no sampling parameters


async def test_anthropic_retry_prompt_carries_the_validation_error() -> None:
    client, script, _ = make_anthropic([an_tool({"name": "widget"}), an_tool(GOOD)])

    await client.complete_json("describe", Widget)

    retry_user = json.dumps(script.requests[1]["messages"][-1])
    assert "describe" in retry_user
    assert "invalid" in retry_user.lower()
