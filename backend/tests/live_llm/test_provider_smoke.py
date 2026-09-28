"""One live smoke call per provider through its adapter (T08b).

Run with `uv run pytest -m live_llm`. Each case is skipped unless that provider's
key is present in the environment (or the root `.env`). Model comes from
`LLM_MODEL` when `LLM_PROVIDER` matches the provider under test, otherwise from a
provider-specific `<PROVIDER>_SMOKE_MODEL` variable; skipped if neither is set.
Keys are never printed.
"""

from __future__ import annotations

import os

import pytest
from pydantic import BaseModel

from app.config import Settings
from app.llm.providers.anthropic import AnthropicProvider
from app.llm.providers.base import BaseProvider
from app.llm.providers.groq import GroqProvider
from app.llm.providers.openai import OpenAIProvider

pytestmark = pytest.mark.live_llm

_ADAPTERS: dict[str, type[BaseProvider]] = {
    "openai": OpenAIProvider,
    "groq": GroqProvider,
    "anthropic": AnthropicProvider,
}


class _Ping(BaseModel):
    word: str


def _key_and_model(provider: str) -> tuple[str, str]:
    settings = Settings()
    key = getattr(settings, f"{provider}_api_key")
    if not key:
        pytest.skip(f"{provider.upper()}_API_KEY not set")
    model = (
        settings.llm_model
        if settings.llm_provider == provider
        else os.environ.get(f"{provider.upper()}_SMOKE_MODEL")
    )
    if not model:
        pytest.skip(f"no model for {provider}: set LLM_PROVIDER={provider} or "
                    f"{provider.upper()}_SMOKE_MODEL")
    return key, model


@pytest.mark.parametrize("provider", ["openai", "groq", "anthropic"])
async def test_complete_json_and_text_smoke(provider: str) -> None:
    key, model = _key_and_model(provider)
    client = _ADAPTERS[provider](api_key=key, model=model)

    result = await client.complete_json('Return the word "pong".', _Ping)
    text = await client.complete_text("Reply with exactly one word: pong.")

    assert result.word.strip()
    assert text.strip()
