"""Shared retry / timeout / error-mapping logic for provider adapters.

Adapters implement only the raw request (`_request_json`, `_request_text`) and
`_classify_error`; this base owns the behavior every provider must share:

- Invalid JSON, or JSON that fails Pydantic validation: one retry with the validation
  error appended to the prompt, then `LLMInvalidOutputError` ("the job fails loudly").
- A call exceeding the timeout (30 s, docs/technical-design.md "LLM usage"):
  `LLMTimeoutError`. Not retried; the docs only specify retries for invalid output
  and 429.
- HTTP 429: exponential backoff (`base * 2**attempt`) and retry, then
  `RateLimitedError` once retries are exhausted.

Provider SDKs must be configured with their own retries off (`max_retries=0`) so this
class owns backoff and behavior stays deterministic and testable.
"""

from __future__ import annotations

import abc
import asyncio
import enum
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.core.errors import LLMInvalidOutputError, LLMTimeoutError, RateLimitedError
from app.llm.client import LLMClient

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")

# docs/technical-design.md "LLM usage": "30 s per call, surfaced as llm_timeout errors".
DEFAULT_TIMEOUT_SECONDS = 30.0

# Not specified in the docs; 3 retries with a 1 s base waits 1 s, 2 s, 4 s (~7 s) so bulk
# seeding survives a short burst of throttling without hanging indefinitely.
DEFAULT_MAX_RATE_LIMIT_RETRIES = 3
DEFAULT_BACKOFF_BASE_SECONDS = 1.0

SleepFn = Callable[[float], Awaitable[None]]


class ErrorKind(enum.Enum):
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"


class BaseProvider(LLMClient):
    """Retry/error-mapping skeleton; subclasses talk to exactly one provider SDK."""

    provider_name: str

    def __init__(
        self,
        *,
        model: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_rate_limit_retries: int = DEFAULT_MAX_RATE_LIMIT_RETRIES,
        backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
        sleep: SleepFn = asyncio.sleep,
    ) -> None:
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_rate_limit_retries = max_rate_limit_retries
        self._backoff_base_seconds = backoff_base_seconds
        self._sleep = sleep

    # --- adapter hooks -------------------------------------------------------

    @abc.abstractmethod
    async def _request_json(
        self, prompt: str, schema: type[BaseModel], temperature: float, system: str | None
    ) -> str:
        """One structured request; return the model's JSON as a string."""

    @abc.abstractmethod
    async def _request_text(self, prompt: str, temperature: float, system: str | None) -> str:
        """One plain-text request; return the response text."""

    @abc.abstractmethod
    def _classify_error(self, exc: Exception) -> ErrorKind | None:
        """Map an SDK exception to a timeout / rate-limit kind, or None to re-raise it."""

    # --- public interface ----------------------------------------------------

    async def complete_json(
        self,
        prompt: str,
        schema: type[T],
        *,
        temperature: float = 0.0,
        system: str | None = None,
    ) -> T:
        current_prompt = prompt
        last_error: Exception | None = None

        for attempt in range(2):  # original call + exactly one retry on invalid output
            if last_error is not None:
                current_prompt = (
                    f"{prompt}\n\n"
                    "Your previous response was invalid and failed with this error:\n"
                    f"{last_error}\n\n"
                    "Return only a single corrected JSON object matching the schema above."
                )

            raw = await self._with_backoff(
                self._json_call(current_prompt, schema, temperature, system)
            )

            try:
                return schema.model_validate(json.loads(raw))
            except (json.JSONDecodeError, ValidationError) as exc:
                logger.warning(
                    "llm.invalid_output provider=%s attempt=%d schema=%s error=%s",
                    self.provider_name,
                    attempt,
                    schema.__name__,
                    exc,
                )
                last_error = exc

        raise LLMInvalidOutputError(
            f"{self.provider_name} output failed validation against {schema.__name__} "
            f"after one retry: {last_error}"
        )

    async def complete_text(
        self,
        prompt: str,
        *,
        temperature: float = 0.0,
        system: str | None = None,
    ) -> str:
        return await self._with_backoff(lambda: self._request_text(prompt, temperature, system))

    # --- internals -----------------------------------------------------------

    def _json_call(
        self, prompt: str, schema: type[BaseModel], temperature: float, system: str | None
    ) -> Callable[[], Awaitable[str]]:
        return lambda: self._request_json(prompt, schema, temperature, system)

    async def _with_backoff(self, call: Callable[[], Awaitable[R]]) -> R:
        """Run one provider request, mapping timeouts and retrying 429s with backoff."""
        attempt = 0
        while True:
            start = time.monotonic()
            try:
                result = await call()
            except Exception as exc:
                kind = self._classify_error(exc)
                duration = time.monotonic() - start
                if kind is ErrorKind.TIMEOUT:
                    logger.warning(
                        "llm.timeout provider=%s model=%s timeout=%.1fs duration=%.2fs",
                        self.provider_name,
                        self._model,
                        self._timeout_seconds,
                        duration,
                    )
                    raise LLMTimeoutError(
                        f"{self.provider_name} call exceeded the {self._timeout_seconds}s timeout."
                    ) from exc
                if kind is ErrorKind.RATE_LIMIT:
                    if attempt >= self._max_rate_limit_retries:
                        logger.warning(
                            "llm.rate_limited giving_up provider=%s model=%s attempts=%d "
                            "duration=%.2fs",
                            self.provider_name,
                            self._model,
                            attempt + 1,
                            duration,
                        )
                        raise RateLimitedError(
                            f"{self.provider_name} rate limit exceeded after retries."
                        ) from exc
                    delay = self._backoff_base_seconds * (2**attempt)
                    logger.info(
                        "llm.rate_limited retrying provider=%s model=%s attempt=%d "
                        "delay=%.2fs duration=%.2fs",
                        self.provider_name,
                        self._model,
                        attempt,
                        delay,
                        duration,
                    )
                    await self._sleep(delay)
                    attempt += 1
                    continue
                raise

            logger.info(
                "llm.call provider=%s model=%s duration=%.2fs",
                self.provider_name,
                self._model,
                time.monotonic() - start,
            )
            return result


def json_schema_instruction(schema: type[BaseModel]) -> str:
    """Prompt text telling a JSON-mode model to match the Pydantic model's schema."""
    return (
        "Respond with a single JSON object only - no markdown fences, no commentary - "
        f"that strictly matches this JSON Schema:\n{json.dumps(schema.model_json_schema())}"
    )
