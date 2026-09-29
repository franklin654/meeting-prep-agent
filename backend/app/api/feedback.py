"""Feedback and style endpoints (ticket T19)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_memory_service, get_session_factory
from app.db.feedback_repo import delete_all_feedback, delete_feedback_for_section
from app.memory.memory_service import MemoryService
from app.schemas.api import FeedbackRequest, StyleProfile
from app.schemas.brief import SectionKey
from app.services.ingest import SessionFactory
from app.services.preferences import current_style, record_feedback

router = APIRouter()

MemoryDep = Annotated[MemoryService, Depends(get_memory_service)]
SessionFactoryDep = Annotated[SessionFactory, Depends(get_session_factory)]


@router.post("/briefs/{brief_id}/feedback", response_model=StyleProfile)
async def post_feedback(
    brief_id: str,
    body: FeedbackRequest,
    memory: MemoryDep,
    session_factory: SessionFactoryDep,
) -> StyleProfile:
    """Store the feedback row, retain one preference sentence, return the new profile."""
    return await record_feedback(session_factory, memory, brief_id, body)


@router.get("/style", response_model=StyleProfile)
async def get_style(session_factory: SessionFactoryDep) -> StyleProfile:
    """The style profile derived from every feedback row."""
    return current_style(session_factory)


@router.post("/style/reset", response_model=StyleProfile)
async def reset_style(session_factory: SessionFactoryDep) -> StyleProfile:
    """Clear all app feedback rows and return the default style profile."""
    delete_all_feedback(session_factory)
    return current_style(session_factory)


@router.delete("/style/rules/{section}", response_model=StyleProfile)
async def delete_style_rule(
    section: SectionKey, session_factory: SessionFactoryDep
) -> StyleProfile:
    """Remove the feedback history for one section and return the updated style profile."""
    delete_feedback_for_section(session_factory, section)
    return current_style(session_factory)
