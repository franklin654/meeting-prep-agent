"""Brief endpoints (docs/technical-design.md "API routes"; ticket T15).

POST always generates a fresh brief (the explicit refresh; the service upserts the record
for meeting and mode). GET only reads the cache and never generates.
"""

from __future__ import annotations

import logging
import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends

from app.api.deps import get_brief_llm, get_memory_service, get_session_factory
from app.core.errors import NotFoundError
from app.llm.client import LLMClient
from app.memory.memory_service import MemoryService
from app.schemas.brief import Brief
from app.services.brief import generate_brief, get_cached_brief
from app.services.ingest import SessionFactory

logger = logging.getLogger(__name__)

router = APIRouter()

LlmDep = Annotated[LLMClient, Depends(get_brief_llm)]
MemoryDep = Annotated[MemoryService, Depends(get_memory_service)]
SessionFactoryDep = Annotated[SessionFactory, Depends(get_session_factory)]
Mode = Literal["memory", "no_memory"]


def _log(verb: str, meeting_id: str, mode: str, started: float, outcome: str) -> None:
    logger.info(
        "brief.%s meeting=%s mode=%s outcome=%s duration=%dms",
        verb,
        meeting_id,
        mode,
        outcome,
        (time.monotonic() - started) * 1000,
    )


@router.post("/meetings/{meeting_id}/brief", response_model=Brief)
async def create_brief(
    meeting_id: str,
    llm: LlmDep,
    memory: MemoryDep,
    session_factory: SessionFactoryDep,
    mode: Mode = "memory",
) -> Brief:
    """Generate a fresh brief for the meeting, replacing any stored one for this mode."""
    started = time.monotonic()
    try:
        brief = await generate_brief(
            meeting_id, mode, llm=llm, memory=memory, session_factory=session_factory
        )
    except Exception as exc:
        _log("generate", meeting_id, mode, started, type(exc).__name__)
        raise
    if not brief.sections:
        logger.warning("brief.empty meeting=%s mode=%s: no sections generated", meeting_id, mode)
    _log("generate", meeting_id, mode, started, "ok")
    return brief


@router.get("/meetings/{meeting_id}/brief", response_model=Brief)
async def read_brief(
    meeting_id: str,
    session_factory: SessionFactoryDep,
    mode: Mode = "memory",
) -> Brief:
    """The stored brief; 404 when none exists or a later ingest made it stale."""
    started = time.monotonic()
    brief = await get_cached_brief(meeting_id, mode, session_factory=session_factory)
    if brief is None:
        _log("read", meeting_id, mode, started, "miss")
        raise NotFoundError(f"No fresh {mode} brief for meeting {meeting_id!r}.")
    _log("read", meeting_id, mode, started, "hit")
    return brief
