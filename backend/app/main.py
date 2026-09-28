"""FastAPI app entrypoint: app creation, router registration, error handlers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.core.errors import register_exception_handlers


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Fail fast at startup on invalid LLM config (app and Hindsight).

    Raises `ConfigError` naming the variable, never its value. Later tickets add
    gateway startup/shutdown around the `yield`.
    """
    settings.validate_llm_config()
    yield


app = FastAPI(title="Meeting Prep Agent API", lifespan=lifespan)

register_exception_handlers(app)


@app.get("/api/health")
async def health() -> dict[str, str]:
    """Liveness stub.

    Full dependency checks (Hindsight, DB) land with the memory and db gateways
    (T06, T07); for now this only proves the API process is up.
    """
    return {"status": "ok"}
