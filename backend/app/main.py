"""FastAPI app entrypoint: app creation, router registration, error handlers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI

from app.api import ask, briefs, contacts, feedback, jobs, meetings, nudges
from app.api.deps import close_memory_service
from app.config import settings
from app.core.errors import register_exception_handlers
from app.db.session import create_db_and_tables


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Fail fast at startup on invalid LLM config (app and Hindsight).

    Raises `ConfigError` naming the variable, never its value. Later tickets add
    gateway startup/shutdown around the `yield`.
    """
    settings.validate_llm_config()
    create_db_and_tables()  # idempotent: a fresh DB works without `make reset-demo`
    try:
        yield
    finally:
        await close_memory_service()  # no-op unless a request created it


app = FastAPI(title="Meeting Prep Agent API", lifespan=lifespan)

register_exception_handlers(app)
app.include_router(meetings.router, prefix="/api")
app.include_router(ask.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(briefs.router, prefix="/api")
app.include_router(feedback.router, prefix="/api")
app.include_router(contacts.router, prefix="/api")
app.include_router(nudges.router, prefix="/api")


@app.get("/api/health")
async def health() -> dict[str, str | date]:
    """Liveness stub.

    Full dependency checks (Hindsight, DB) land with the memory and db gateways
    (T06, T07); for now this only proves the API process is up.
    """
    return {"status": "ok", "demo_today": settings.demo_today}
