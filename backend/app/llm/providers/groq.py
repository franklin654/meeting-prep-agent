"""Groq adapter: OpenAI-compatible chat API with JSON mode (behavior unchanged from T08)."""

from __future__ import annotations

from typing import Any

import groq
from pydantic import BaseModel

from app.llm.providers.base import (
    DEFAULT_BACKOFF_BASE_SECONDS,
    DEFAULT_MAX_RATE_LIMIT_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    BaseProvider,
    ErrorKind,
    SleepFn,
    json_schema_instruction,
)


def _messages(prompt: str, system: str | None) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return messages


class GroqProvider(BaseProvider):
    provider_name = "groq"

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
        # max_retries=0: BaseProvider owns 429 backoff. Typed `Any` so tests can inject a
        # stub that duck-types `.chat.completions.create(...)`.
        self._client: Any = (
            client if client is not None else groq.AsyncGroq(api_key=api_key, max_retries=0)
        )

    async def _request_json(
        self, prompt: str, schema: type[BaseModel], temperature: float, system: str | None
    ) -> str:
        instruction = json_schema_instruction(schema)
        system_content = f"{system}\n\n{instruction}" if system else instruction
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=_messages(prompt, system_content),
            temperature=temperature,
            response_format={"type": "json_object"},
            timeout=self._timeout_seconds,
        )
        return str(response.choices[0].message.content or "")

    async def _request_text(self, prompt: str, temperature: float, system: str | None) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=_messages(prompt, system),
            temperature=temperature,
            timeout=self._timeout_seconds,
        )
        return str(response.choices[0].message.content or "")

    def _classify_error(self, exc: Exception) -> ErrorKind | None:
        if isinstance(exc, groq.APITimeoutError):
            return ErrorKind.TIMEOUT
        if isinstance(exc, groq.RateLimitError):
            return ErrorKind.RATE_LIMIT
        return None
