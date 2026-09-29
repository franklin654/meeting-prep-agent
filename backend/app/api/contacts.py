"""Contact endpoints (docs/technical-design.md "API routes"; ticket T18)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import get_memory_service, get_session
from app.memory.memory_service import MemoryService
from app.schemas.api import ContactTimeline
from app.services.timeline import build_timeline

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]
MemoryDep = Annotated[MemoryService, Depends(get_memory_service)]


@router.get("/contacts/{contact_id}/timeline", response_model=ContactTimeline)
async def contact_timeline(
    contact_id: str, session: SessionDep, memory: MemoryDep
) -> ContactTimeline:
    """Everything memory knows about a contact, newest meeting first, deduplicated, max 30."""
    return await build_timeline(contact_id, session=session, memory=memory)
