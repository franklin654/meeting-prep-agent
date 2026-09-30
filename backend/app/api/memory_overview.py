"""Memory inspector read-only overview endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_memory_service, get_session_factory
from app.memory.memory_service import MemoryService
from app.schemas.api import MemoryOverview
from app.services.ingest import SessionFactory
from app.services.memory_overview import get_memory_overview

router = APIRouter()
MemoryDep = Annotated[MemoryService, Depends(get_memory_service)]
SessionFactoryDep = Annotated[SessionFactory, Depends(get_session_factory)]


@router.get("/memory/overview", response_model=MemoryOverview)
async def read_memory_overview(
    memory: MemoryDep, session_factory: SessionFactoryDep
) -> MemoryOverview:
    return await get_memory_overview(session_factory, memory)
