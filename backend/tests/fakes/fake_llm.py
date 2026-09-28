"""In-memory `LLMClient` double for unit tests. No network calls, ever.

Mirrors how docs/hindsight-integration.md describes `FakeMemoryService`: canned
responses are registered per test and handed back in order, rather than inferred
from the prompt. Used by every service unit test that needs an LLM (ingest, brief,
Ask), per docs/technical-design.md "Testing and quality gates".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

from app.llm.client import LLMClient

T = TypeVar("T", bound=BaseModel)


@dataclass
class RecordedCall:
    """One `complete_json` call, kept for test assertions."""

    prompt: str
    schema: type[BaseModel]
    temperature: float
    system: str | None


@dataclass
class RecordedTextCall:
    """One `complete_text` call, kept for test assertions."""

    prompt: str
    temperature: float
    system: str | None


class FakeLLM(LLMClient):
    """Returns pre-registered responses/errors in FIFO order; records every call."""

    def __init__(self) -> None:
        self._queue: list[BaseModel | Exception] = []
        self.calls: list[RecordedCall] = []
        self._text_queue: list[str | Exception] = []
        self.text_calls: list[RecordedTextCall] = []

    def queue_text(self, text: str) -> None:
        """Register a plain-text response for the next `complete_text` call."""
        self._text_queue.append(text)

    def queue_text_error(self, error: Exception) -> None:
        """Register an exception to raise on the next `complete_text` call."""
        self._text_queue.append(error)

    async def complete_text(
        self,
        prompt: str,
        *,
        temperature: float = 0.0,
        system: str | None = None,
    ) -> str:
        self.text_calls.append(
            RecordedTextCall(prompt=prompt, temperature=temperature, system=system)
        )
        if not self._text_queue:
            raise AssertionError(
                "FakeLLM.complete_text called with no canned response queued. "
                "Call queue_text()/queue_text_error() in the test first."
            )
        item = self._text_queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def queue_response(self, response: BaseModel) -> None:
        """Register a response to return on the next `complete_json` call."""
        self._queue.append(response)

    def queue_error(self, error: Exception) -> None:
        """Register an exception to raise on the next `complete_json` call."""
        self._queue.append(error)

    async def complete_json(
        self,
        prompt: str,
        schema: type[T],
        *,
        temperature: float = 0.0,
        system: str | None = None,
    ) -> T:
        self.calls.append(
            RecordedCall(prompt=prompt, schema=schema, temperature=temperature, system=system)
        )
        if not self._queue:
            raise AssertionError(
                f"FakeLLM.complete_json called with no canned response queued "
                f"for {schema.__name__}. Call queue_response()/queue_error() in the test first."
            )
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        if not isinstance(item, schema):
            raise AssertionError(
                f"FakeLLM was queued a {type(item).__name__}, but the caller expected "
                f"{schema.__name__}."
            )
        return item
