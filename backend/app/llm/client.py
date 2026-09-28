"""LLM gateway: the interface every app LLM call goes through, plus the provider factory.

AGENTS.md hard rule 1: app code calls an LLM only via `LLMClient`. Provider SDKs
(openai, groq, anthropic) are imported only inside `app/llm/providers/`; the adapter
is chosen by `LLM_PROVIDER` in `.env` (`get_llm_client`), never hard-coded. Nothing
outside `app/llm/` may depend on which provider is selected.

- `complete_json(prompt, schema)`: structured call, output re-validated with Pydantic.
- `complete_text(prompt)`: plain-text call (e.g. Hindsight-free prose like the G1
  transcript generator).

Retry, timeout and error mapping (`LLMTimeoutError`, `LLMInvalidOutputError`,
`RateLimitedError`) are shared by all adapters in `app/llm/providers/base.py`.

Prompts live in `app/llm/prompts/*.md` (AGENTS.md hard rule 8) and are rendered by
callers before being passed in as the plain `prompt` string.
"""

from __future__ import annotations

import abc
from typing import TypeVar

from pydantic import BaseModel

from app.config import Settings
from app.config import settings as default_settings

T = TypeVar("T", bound=BaseModel)


class LLMClient(abc.ABC):
    """Provider-neutral LLM interface. Adapters and `FakeLLM` implement it."""

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

    @abc.abstractmethod
    async def complete_text(
        self,
        prompt: str,
        *,
        temperature: float = 0.0,
        system: str | None = None,
    ) -> str:
        """Run one plain-text LLM call and return the response text."""


def get_llm_client(config: Settings | None = None) -> LLMClient:
    """Build the adapter for `LLM_PROVIDER`. Fails fast (`ConfigError`) on bad config."""
    config = config or default_settings
    config.validate_app_llm_config()
    api_key = config.app_llm_api_key
    model = config.llm_model

    # Imported lazily: each adapter imports its provider SDK, and this keeps the
    # unselected providers' SDKs out of the process.
    if config.llm_provider == "openai":
        from app.llm.providers.openai import OpenAIProvider

        return OpenAIProvider(api_key=api_key, model=model)
    if config.llm_provider == "groq":
        from app.llm.providers.groq import GroqProvider

        return GroqProvider(api_key=api_key, model=model)
    from app.llm.providers.anthropic import AnthropicProvider

    return AnthropicProvider(api_key=api_key, model=model)
