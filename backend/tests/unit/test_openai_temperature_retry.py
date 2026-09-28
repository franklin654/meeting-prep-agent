"""OpenAI temperature best-effort retry (T08c). Mocked HTTP, no network."""

from __future__ import annotations

import json
import logging
from typing import Any

import openai
import pytest

from app.core.errors import RateLimitedError
from tests.unit.test_llm_providers_http import (
    GOOD,
    RATE_LIMITED,
    Widget,
    make_openai,
    oa_ok,
)

TEMP_400 = (
    400,
    {
        "error": {
            "message": "Unsupported value: 'temperature' does not support 0.0 with this model. "
            "Only the default (1) value is supported.",
            "type": "invalid_request_error",
            "param": "temperature",
            "code": "unsupported_value",
        }
    },
)
TEMP_400_PARAM = (
    400,
    {
        "error": {
            "message": "Unsupported parameter: 'temperature' is not supported with this model.",
            "type": "invalid_request_error",
        }
    },
)
OTHER_400 = (
    400,
    {"error": {"message": "Invalid schema for response_format.", "type": "invalid_request_error"}},
)


@pytest.mark.parametrize("bad", [TEMP_400, TEMP_400_PARAM], ids=["value", "parameter"])
async def test_json_drops_temperature_and_retries_once(
    bad: Any, caplog: pytest.LogCaptureFixture
) -> None:
    client, script, _ = make_openai([bad, oa_ok(json.dumps(GOOD))])
    with caplog.at_level(logging.WARNING):
        result = await client.complete_json("go", Widget)

    assert result == Widget(name="widget", count=3)
    assert "temperature" in script.requests[0]
    assert "temperature" not in script.requests[1]
    assert script.requests[1]["messages"] == script.requests[0]["messages"]
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("temperature" in w and "openai" in w and "test-model" in w for w in warnings)
    assert "not-a-real-key" not in caplog.text
    assert "go" not in " ".join(warnings).split()  # no prompt content


async def test_text_drops_temperature_and_retries_once() -> None:
    client, script, _ = make_openai([TEMP_400, oa_ok("hello")])
    assert await client.complete_text("go") == "hello"
    assert "temperature" in script.requests[0]
    assert "temperature" not in script.requests[1]


async def test_other_400_is_not_retried() -> None:
    client, script, _ = make_openai([OTHER_400])
    with pytest.raises(openai.BadRequestError):
        await client.complete_json("go", Widget)
    assert len(script.requests) == 1


async def test_second_temperature_400_surfaces_no_loop() -> None:
    client, script, _ = make_openai([TEMP_400, TEMP_400])
    with pytest.raises(openai.BadRequestError):
        await client.complete_text("go")
    assert len(script.requests) == 2
    assert "temperature" not in script.requests[1]


async def test_budgets_are_independent_of_429_backoff() -> None:
    # 429 -> temp 400 -> 429 -> ok: the temperature retry does not consume 429 retries.
    client, script, clock = make_openai(
        [RATE_LIMITED, TEMP_400, RATE_LIMITED, oa_ok("fine")], max_rate_limit_retries=2
    )
    assert await client.complete_text("go") == "fine"
    assert clock.delays == [1.0, 2.0]

    client, _, _ = make_openai(
        [TEMP_400, RATE_LIMITED, RATE_LIMITED, RATE_LIMITED], max_rate_limit_retries=2
    )
    with pytest.raises(RateLimitedError):
        await client.complete_text("go")


async def test_invalid_output_retry_keeps_temperature_dropped_without_extra_budget() -> None:
    client, script, _ = make_openai([TEMP_400, oa_ok("not json"), oa_ok(json.dumps(GOOD))])
    assert (await client.complete_json("go", Widget)).count == 3
    assert len(script.requests) == 3
    assert "temperature" not in script.requests[2]
