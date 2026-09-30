"""Contact endpoints (docs/technical-design.md "API routes"; ticket T18)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import get_brief_llm, get_memory_service, get_session, get_session_factory
from app.db.brief_repo import SessionFactory
from app.llm.client import LLMClient
from app.memory.memory_service import MemoryService
from app.schemas.api import ContactProfile, ContactTimeline
from app.schemas.patterns import PatternRefreshResponse
from app.services.profile import build_contact_profile, refresh_contact_patterns
from app.services.timeline import build_timeline

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]
MemoryDep = Annotated[MemoryService, Depends(get_memory_service)]
FactoryDep = Annotated[SessionFactory, Depends(get_session_factory)]
LlmDep = Annotated[LLMClient, Depends(get_brief_llm)]


@router.get("/contacts/{contact_id}/timeline", response_model=ContactTimeline)
async def contact_timeline(
    contact_id: str, session: SessionDep, memory: MemoryDep
) -> ContactTimeline:
    """Everything memory knows about a contact, newest meeting first, deduplicated, max 30."""
    return await build_timeline(contact_id, session=session, memory=memory)


@router.get("/contacts/{contact_id}/profile", response_model=ContactProfile)
def contact_profile(contact_id: str, session_factory: FactoryDep) -> ContactProfile:
    return build_contact_profile(contact_id, session_factory=session_factory)


@router.post(
    "/contacts/{contact_id}/patterns/refresh", response_model=PatternRefreshResponse
)
async def refresh_patterns(
    contact_id: str, llm: LlmDep, session_factory: FactoryDep
) -> PatternRefreshResponse:
    return await refresh_contact_patterns(contact_id, llm=llm, session_factory=session_factory)
