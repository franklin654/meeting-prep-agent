"""Anthropic adapter: a forced tool call whose `input_schema` is the Pydantic JSON schema."""

from __future__ import annotations

import json
from typing import Any

import anthropic
from pydantic import BaseModel

from app.llm.providers.base import (
    DEFAULT_BACKOFF_BASE_SECONDS,
    DEFAULT_MAX_RATE_LIMIT_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    BaseProvider,
    ErrorKind,
    SleepFn,
)

_TOOL_NAME = "respond"
# The Messages API requires max_tokens; generous enough for a full brief or extraction.
_MAX_TOKENS = 4096

# `temperature` is accepted by the LLMClient interface but deliberately NOT sent: the
# installed anthropic SDK's `messages.create` has no sampling parameters (temperature,
# top_p, top_k are gone), so passing it raises TypeError. Determinism for extraction
# therefore relies on the forced tool call and schema re-validation.


class AnthropicProvider(BaseProvider):
    provider_name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_rate_limit_retries: int = DEFAULT_MAX_RATE_LIMIT_RETRIES,
        backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
        client: Any | None = None,
        sleep: SleepFn | None = None,
    ) -> None:
        super().__init__(
            model=model,
            timeout_seconds=timeout_seconds,
            max_rate_limit_retries=max_rate_limit_retries,
            backoff_base_seconds=backoff_base_seconds,
            **({"sleep": sleep} if sleep else {}),
        )
        self._client: Any = (
            client
            if client is not None
            else anthropic.AsyncAnthropic(api_key=api_key, max_retries=0)
        )

    async def _request_json(
        self, prompt: str, schema: type[BaseModel], temperature: float, system: str | None
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": _MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [
                {
                    "name": _TOOL_NAME,
                    "description": f"Return the {schema.__name__} result.",
                    "input_schema": schema.model_json_schema(),
                }
            ],
            "tool_choice": {"type": "tool", "name": _TOOL_NAME},
            "timeout": self._timeout_seconds,
        }
        if system:
            kwargs["system"] = system
        response = await self._client.messages.create(**kwargs)
        for block in response.content:
            if block.type == "tool_use":
                return json.dumps(block.input)
        return ""  # no tool call: fails validation and takes the invalid-output retry path

    async def _request_text(self, prompt: str, temperature: float, system: str | None) -> str:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": _MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
            "timeout": self._timeout_seconds,
        }
        if system:
            kwargs["system"] = system
        response = await self._client.messages.create(**kwargs)
        return "".join(block.text for block in response.content if block.type == "text")

    def _classify_error(self, exc: Exception) -> ErrorKind | None:
        if isinstance(exc, anthropic.APITimeoutError):
            return ErrorKind.TIMEOUT
        if isinstance(exc, anthropic.RateLimitError):
            return ErrorKind.RATE_LIMIT
        return None
