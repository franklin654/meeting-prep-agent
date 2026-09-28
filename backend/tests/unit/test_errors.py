from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.core.errors import (
    LLMInvalidOutputError,
    LLMTimeoutError,
    MemoryUnavailableError,
    NotFoundError,
    RateLimitedError,
    ValidationError,
    register_exception_handlers,
)


def _client_raising(exc: Exception) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise exc

    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    ("exc", "code", "status_code"),
    [
        (NotFoundError("no such meeting"), "not_found", 404),
        (ValidationError("bad body"), "validation_error", 422),
        (MemoryUnavailableError("hindsight down"), "memory_unavailable", 503),
        (LLMTimeoutError("timed out"), "llm_timeout", 504),
        (LLMInvalidOutputError("bad json"), "llm_invalid_output", 502),
        (RateLimitedError("groq 429"), "rate_limited", 429),
    ],
)
def test_app_error_maps_to_standard_shape(exc: Exception, code: str, status_code: int) -> None:
    client = _client_raising(exc)

    response = client.get("/boom")

    assert response.status_code == status_code
    assert response.json() == {"error": {"code": code, "message": str(exc)}}


def test_request_validation_error_uses_standard_shape() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    class Body(BaseModel):
        name: str = Field(min_length=3)

    @app.post("/thing")
    async def thing(body: Body) -> dict[str, str]:
        return {"ok": "true"}

    client = TestClient(app)

    response = client.post("/thing", json={"name": "a"})

    assert response.status_code == 422
    body: dict[str, Any] = response.json()
    assert body["error"]["code"] == "validation_error"
    assert isinstance(body["error"]["message"], str)


def test_unexpected_error_does_not_leak_a_stack_trace() -> None:
    client = _client_raising(RuntimeError("kaboom"))

    response = client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "An unexpected error occurred."}
    }
