"""App configuration, loaded from environment variables (and `.env` if present).

Business logic must read "today" from `settings.demo_today`, never
`date.today()` / `datetime.now()` — see AGENTS.md hard rule 6.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# The repo's single `.env` lives at the repo root (also read by docker-compose.yml
# for its own ${VAR} substitution — there is deliberately no backend/.env). Resolve
# it relative to this file's own location, not the process's cwd, so settings load
# correctly whether the process is started from the repo root, backend/, or elsewhere.
# backend/app/config.py -> .parent = backend/app, .parent.parent = backend,
# .parent.parent.parent = repo root.
_REPO_ROOT_ENV = Path(__file__).resolve().parent.parent.parent / ".env"


SUPPORTED_LLM_PROVIDERS = ("openai", "groq", "anthropic")


class ConfigError(ValueError):
    """Invalid or incomplete configuration. Messages name variables, never values."""


def _check_provider(variable: str, value: str) -> None:
    if value not in SUPPORTED_LLM_PROVIDERS:
        raise ConfigError(
            f"{variable} must be one of {', '.join(SUPPORTED_LLM_PROVIDERS)}; "
            "the configured value is not supported."
        )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT_ENV, env_file_encoding="utf-8", extra="ignore"
    )

    # Demo clock. See docs/technical-design.md ("Config, local dev and deployment").
    demo_today: date = date(2026, 9, 28)
    demo_user_id: str = "priya"

    # Placeholders for env vars named in docs/technical-design.md; the modules that
    # actually use them (db, memory, llm) are built in later tickets (T02, T06-T08).
    database_url: str = "sqlite:///./app.db"
    hindsight_url: str = "http://localhost:8888"

    # App LLM (app/llm/client.py). One key per provider; only the selected provider's
    # key is required. Hindsight's LLM is configured separately (docker-compose.yml maps
    # HINDSIGHT_LLM_* onto Hindsight's own HINDSIGHT_API_LLM_* variables).
    llm_provider: str = "groq"
    llm_model: str = "llama-3.1-8b-instant"
    openai_api_key: str | None = None
    groq_api_key: str | None = None
    anthropic_api_key: str | None = None
    hindsight_llm_provider: str = "groq"
    hindsight_llm_model: str | None = None
    hindsight_llm_api_key: str | None = None
    memory_read_only: bool = False

    @property
    def app_llm_api_key(self) -> str | None:
        """The key for the selected app provider (`None` if unset or provider unknown)."""
        keys = {
            "openai": self.openai_api_key,
            "groq": self.groq_api_key,
            "anthropic": self.anthropic_api_key,
        }
        return keys.get(self.llm_provider) or None

    def validate_llm_config(self) -> None:
        """Fail fast on an unknown provider or a missing key/model, app and Hindsight.

        Errors name the environment variable, never its value. Call at startup;
        `get_llm_client` also calls `validate_app_llm_config` itself.
        """
        self.validate_app_llm_config()
        self.validate_hindsight_llm_config()

    def validate_app_llm_config(self) -> None:
        _check_provider("LLM_PROVIDER", self.llm_provider)
        if not self.llm_model:
            raise ConfigError("LLM_MODEL is not set.")
        if not self.app_llm_api_key:
            raise ConfigError(
                f"{self.llm_provider.upper()}_API_KEY is not set "
                f"(required because LLM_PROVIDER={self.llm_provider})."
            )

    def validate_hindsight_llm_config(self) -> None:
        _check_provider("HINDSIGHT_LLM_PROVIDER", self.hindsight_llm_provider)
        if not self.hindsight_llm_model:
            raise ConfigError("HINDSIGHT_LLM_MODEL is not set.")
        if not self.hindsight_llm_api_key:
            raise ConfigError("HINDSIGHT_LLM_API_KEY is not set.")


settings = Settings()
