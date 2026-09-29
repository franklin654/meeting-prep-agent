"""FastAPI dependencies shared by the routers (ticket T13).

The memory service and the ingest LLM client are built lazily, on first use, never at
import or startup, so the app boots while Hindsight is down. All of these are plain
dependencies: tests replace them with `app.dependency_overrides`.
"""

from __future__ import annotations

from sqlmodel import Session

from app.db import session as db_session
from app.db.session import get_session
from app.llm.client import LLMClient
from app.memory.memory_service import HindsightMemoryService, MemoryService
from app.services.ingest import SessionFactory, default_ingest_llm

__all__ = [
    "close_memory_service",
    "get_llm_client_for_ingest",
    "get_memory_service",
    "get_session",
    "get_session_factory",
]

_memory: HindsightMemoryService | None = None
_ingest_llm: LLMClient | None = None


def get_memory_service() -> MemoryService:
    """Process-wide `HindsightMemoryService`, created on first use."""
    global _memory
    if _memory is None:
        _memory = HindsightMemoryService()
    return _memory


async def close_memory_service() -> None:
    """Close the memory service if one was ever created (lifespan shutdown)."""
    global _memory
    if _memory is not None:
        memory, _memory = _memory, None
        await memory.aclose()


def get_llm_client_for_ingest() -> LLMClient:
    """The app LLM with the 120 s ingest timeout, built on first use."""
    global _ingest_llm
    if _ingest_llm is None:
        _ingest_llm = default_ingest_llm()
    return _ingest_llm


def get_session_factory() -> SessionFactory:
    """Callable returning a context-managed `Session` bound to the engine.

    Background tasks outlive the request, so they get this instead of the
    request-scoped session.
    """
    return lambda: Session(db_session.engine)
