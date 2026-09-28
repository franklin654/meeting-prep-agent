"""FastAPI app entrypoint: app creation, router registration, error handlers."""

from __future__ import annotations

from fastapi import FastAPI

from app.core.errors import register_exception_handlers

app = FastAPI(title="Meeting Prep Agent API")

register_exception_handlers(app)


@app.get("/api/health")
async def health() -> dict[str, str]:
    """Liveness stub.

    Full dependency checks (Hindsight, DB) land with the memory and db gateways
    (T06, T07); for now this only proves the API process is up.
    """
    return {"status": "ok"}
