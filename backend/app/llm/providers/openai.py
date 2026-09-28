"""OpenAI adapter: structured outputs (`json_schema` response format) with the Pydantic schema."""

from __future__ import annotations

from typing import Any

import openai
from pydantic import BaseModel

from app.llm.providers.base import (
    DEFAULT_BACKOFF_BASE_SECONDS,
    DEFAULT_MAX_RATE_LIMIT_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    BaseProvider,
    ErrorKind,
    SleepFn,
)


def _messages(prompt: str, system: str | None) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return messages


class OpenAIProvider(BaseProvider):
    provider_name = "openai"

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
            else openai.AsyncOpenAI(api_key=api_key, max_retries=0)
        )

    async def _request_json(
        self, prompt: str, schema: type[BaseModel], temperature: float, system: str | None
    ) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=_messages(prompt, system),
            temperature=temperature,
            # strict=False: Pydantic schemas are not always strict-mode compatible
            # (optional fields, additionalProperties); output is re-validated anyway.
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": schema.model_json_schema(),
                    "strict": False,
                },
            },
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
        if isinstance(exc, openai.APITimeoutError):
            return ErrorKind.TIMEOUT
        if isinstance(exc, openai.RateLimitError):
            return ErrorKind.RATE_LIMIT
        return None
