"""Groq LLM gateway.

AGENTS.md hard rule 1: only this module imports the `groq` SDK. Every app call is
structured-only (docs/technical-design.md "LLM usage"): `complete_json(prompt, schema)`
sends the prompt plus the Pydantic model's JSON schema to Groq's JSON mode, parses the
response, and re-validates it with that model.

Failure modes map to the typed errors in `app.core.errors`:
- Invalid JSON, or JSON that fails schema validation: one retry with the validation
  error appended to the prompt, then `LLMInvalidOutputError` ("the job fails loudly").
- A call that exceeds the timeout: `LLMTimeoutError`. Not retried — the docs only
  specify retries for invalid JSON and 429, so a timeout is treated as a hard failure.
- Groq returns HTTP 429: exponential backoff and retry (count/base configurable,
  see `DEFAULT_MAX_RATE_LIMIT_RETRIES` / `DEFAULT_BACKOFF_BASE_SECONDS`), then
  `RateLimitedError` if still rate limited after retries are exhausted.

Prompts themselves live in `app/llm/prompts/*.md` (AGENTS.md hard rule 8) and are
rendered by callers (services/ingest.py, services/brief.py, later tickets) before
being passed in as the plain `prompt` string here; this module only adds the JSON
schema instruction and the retry-with-error framing.
"""

from __future__ import annotations

import abc
import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import groq
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.core.errors import LLMInvalidOutputError, LLMTimeoutError, RateLimitedError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# docs/technical-design.md "LLM usage": "30 s per call, surfaced as llm_timeout errors".
DEFAULT_TIMEOUT_SECONDS = 30.0

# Not specified in the docs; chosen so bulk seeding (docs/technical-design.md's note
# that "the seed script retains meetings one at a time with a pause and retry on 429")
# survives a short burst of free-tier throttling without hanging indefinitely.
# 3 retries with a 1s base means waits of 1s, 2s, 4s (~7s total) before giving up.
DEFAULT_MAX_RATE_LIMIT_RETRIES = 3
DEFAULT_BACKOFF_BASE_SECONDS = 1.0

SleepFn = Callable[[float], Awaitable[None]]


class LLMClient(abc.ABC):
    """Interface shared by `GroqLLMClient` and `FakeLLM` (tests/fakes/fake_llm.py)."""

    @abc.abstractmethod
    async def complete_json(
        self,
        prompt: str,
        schema: type[T],
        *,
        temperature: float = 0.0,
        system: str | None = None,
    ) -> T:
        """Run one structured LLM call and return a schema-validated instance of `schema`.

        `temperature` is caller-supplied (0 for extraction, ~0.3 for brief wording per
        docs/technical-design.md), never hardcoded here. `system` is optional extra
        system-prompt context; the JSON-schema instruction is always added by the
        implementation regardless.
        """
        raise NotImplementedError


class GroqLLMClient(LLMClient):
    """Structured-only Groq gateway. The only class that talks to the Groq SDK."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_rate_limit_retries: int = DEFAULT_MAX_RATE_LIMIT_RETRIES,
        backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
        client: Any | None = None,
        sleep: SleepFn = asyncio.sleep,
    ) -> None:
        self._model = model or settings.llm_model
        self._timeout_seconds = timeout_seconds
        self._max_rate_limit_retries = max_rate_limit_retries
        self._backoff_base_seconds = backoff_base_seconds
        self._sleep = sleep
        # max_retries=0: this client owns 429 backoff itself (see `_call_with_backoff`)
        # instead of the SDK's built-in retry, so behavior is deterministic and testable.
        # Typed `Any`: tests inject a lightweight stub (see tests/unit/test_llm_client.py)
        # that duck-types `.chat.completions.create(...)` rather than a real `AsyncGroq`.
        self._client: Any = (
            client if client is not None else groq.AsyncGroq(
                api_key=api_key or settings.llm_api_key, max_retries=0
            )
        )

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

            raw = await self._call_with_backoff(
                current_prompt, schema=schema, temperature=temperature, system=system
            )

            try:
                data = json.loads(raw)
                return schema.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as exc:
                logger.warning(
                    "llm.invalid_output attempt=%d schema=%s error=%s",
                    attempt,
                    schema.__name__,
                    exc,
                )
                last_error = exc
                continue

        raise LLMInvalidOutputError(
            f"Groq output failed validation against {schema.__name__} after one retry: "
            f"{last_error}"
        )

    async def _call_with_backoff(
        self,
        prompt: str,
        *,
        schema: type[BaseModel],
        temperature: float,
        system: str | None,
    ) -> str:
        """One prompt -> one raw response string, retrying on 429 with backoff."""
        messages = _build_messages(prompt, schema, system)
        attempt = 0
        while True:
            start = time.monotonic()
            try:
                response = await self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                    timeout=self._timeout_seconds,
                )
            except groq.APITimeoutError as exc:
                duration = time.monotonic() - start
                logger.warning(
                    "llm.timeout model=%s timeout=%.1fs duration=%.2fs",
                    self._model,
                    self._timeout_seconds,
                    duration,
                )
                raise LLMTimeoutError(
                    f"Groq call exceeded the {self._timeout_seconds}s timeout."
                ) from exc
            except groq.RateLimitError as exc:
                duration = time.monotonic() - start
                if attempt >= self._max_rate_limit_retries:
                    logger.warning(
                        "llm.rate_limited giving_up model=%s attempts=%d duration=%.2fs",
                        self._model,
                        attempt + 1,
                        duration,
                    )
                    raise RateLimitedError(
                        "Groq rate limit exceeded after retries."
                    ) from exc
                delay = self._backoff_base_seconds * (2**attempt)
                logger.info(
                    "llm.rate_limited retrying model=%s attempt=%d delay=%.2fs duration=%.2fs",
                    self._model,
                    attempt,
                    delay,
                    duration,
                )
                await self._sleep(delay)
                attempt += 1
                continue

            duration = time.monotonic() - start
            logger.info("llm.call model=%s duration=%.2fs", self._model, duration)
            content = response.choices[0].message.content
            return content or ""


def _build_messages(
    prompt: str, schema: type[BaseModel], system: str | None
) -> list[dict[str, str]]:
    """System + user messages: JSON-schema instruction, then the caller's prompt verbatim."""
    schema_json = json.dumps(schema.model_json_schema())
    schema_instruction = (
        "Respond with a single JSON object only - no markdown fences, no commentary - "
        f"that strictly matches this JSON Schema:\n{schema_json}"
    )
    system_content = f"{system}\n\n{schema_instruction}" if system else schema_instruction
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": prompt},
    ]
