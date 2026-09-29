"""Typed application errors and the handlers that map them to the API's error shape.

Every error response is `{"error": {"code": "...", "message": "..."}}`
(see docs/data-model-and-schemas.md `ErrorResponse` / `ErrorBody` and the error
code table). Services and routers raise the typed errors below; routers never
build the error response shape by hand.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base class for typed application errors.

    Subclasses declare `code` (from the error code table) and `status_code`;
    `register_exception_handlers` turns any `AppError` into the standard
    error response shape.
    """

    code: str
    status_code: int

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(AppError):
    """Unknown meeting, contact, brief or job."""

    code = "not_found"
    status_code = status.HTTP_404_NOT_FOUND


class ValidationError(AppError):
    """Request body fails its model, raised explicitly by service code."""

    code = "validation_error"
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT


class MemoryUnavailableError(AppError):
    """Hindsight unreachable or timing out."""

    code = "memory_unavailable"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE


class MemoryReadOnlyError(AppError):
    """A request attempted a Hindsight write while read-only mode is enabled."""

    code = "memory_read_only"
    status_code = status.HTTP_409_CONFLICT


class LLMTimeoutError(AppError):
    """LLM call exceeded the 30s timeout."""

    code = "llm_timeout"
    status_code = status.HTTP_504_GATEWAY_TIMEOUT


class LLMInvalidOutputError(AppError):
    """LLM output failed validation after one retry."""

    code = "llm_invalid_output"
    status_code = status.HTTP_502_BAD_GATEWAY


class RateLimitedError(AppError):
    """Groq returned 429 after retries."""

    code = "rate_limited"
    status_code = status.HTTP_429_TOO_MANY_REQUESTS


def _error_response(*, code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


async def _handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return _error_response(code=exc.code, message=exc.message, status_code=exc.status_code)


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return _error_response(
        code="validation_error",
        message="Request failed validation.",
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # Defensive fallback for anything not raised as a typed AppError. Not part of
    # the error code table in docs/data-model-and-schemas.md; kept so the API
    # never leaks a stack trace, only the standard error shape.
    return _error_response(
        code="internal_error",
        message="An unexpected error occurred.",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register the handlers that give every error response the standard shape."""
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)
