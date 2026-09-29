"""OpenAI adapter: structured outputs (`json_schema` response format) with the Pydantic schema."""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


def _names_temperature(exc: openai.BadRequestError) -> bool:
    """True when a 400 says `temperature` is unsupported for this model."""
    return "temperature" in str(exc.message).lower()


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
        # Learned once a model rejects `temperature`; later requests omit it up front.
        self._omit_temperature = False
        self._client: Any = (
            client
            if client is not None
            else openai.AsyncOpenAI(api_key=api_key, max_retries=0)
        )

    async def _request_json(
        self, prompt: str, schema: type[BaseModel], temperature: float, system: str | None
    ) -> str:
        response = await self._create(
            temperature,
            messages=_messages(prompt, system),
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
        )
        self._log_usage(response, call_type="json")
        return str(response.choices[0].message.content or "")

    async def _request_text(self, prompt: str, temperature: float, system: str | None) -> str:
        response = await self._create(temperature, messages=_messages(prompt, system))
        self._log_usage(response, call_type="text")
        return str(response.choices[0].message.content or "")

    async def _create(self, temperature: float, **kwargs: Any) -> Any:
        """One chat completion; best-effort drop of `temperature` if the model rejects it.

        The temperature retry is local to this request, so it never consumes the 429
        backoff or invalid-output budgets owned by `BaseProvider`.
        """
        call = self._client.chat.completions.create
        common: dict[str, Any] = {
            "model": self._model,
            "timeout": self._timeout_seconds,
            **kwargs,
        }
        if self._omit_temperature:
            return await call(**common)
        try:
            return await call(temperature=temperature, **common)
        except openai.BadRequestError as exc:
            if not _names_temperature(exc):
                raise
            logger.warning(
                "llm.temperature_dropped provider=%s model=%s: temperature unsupported, "
                "retrying once without it",
                self.provider_name,
                self._model,
            )
            self._omit_temperature = True
            return await call(**common)

    def _classify_error(self, exc: Exception) -> ErrorKind | None:
        if isinstance(exc, openai.APITimeoutError):
            return ErrorKind.TIMEOUT
        if isinstance(exc, openai.RateLimitError):
            return ErrorKind.RATE_LIMIT
        return None
