"""App-side memory visibility overrides. Hindsight entries are never deleted."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlmodel import Session

from app.api.deps import get_memory_service, get_session, get_session_factory
from app.core.errors import NotFoundError, ValidationError
from app.db import facts_repo, ingest_repo, overrides_repo, repository
from app.memory.memory_service import MemoryService
from app.schemas.api import JobAccepted, MemoryCorrectionRequest
from app.schemas.ask import NoteRequest
from app.schemas.enums import ScopeType
from app.services.ask import run_note_job
from app.services.ingest import SessionFactory

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]
MemoryDep = Annotated[MemoryService, Depends(get_memory_service)]
FactoryDep = Annotated[SessionFactory, Depends(get_session_factory)]


def _resolve_target(session: Session, target_id: str) -> tuple[ScopeType, str]:
    fact = facts_repo.get_fact(session, target_id)
    if fact is not None:
        if fact.contact_id:
            return ScopeType.contact, fact.contact_id
        return ScopeType.account, fact.account_id
    if repository.get_meeting(session, target_id) is not None:
        return ScopeType.meeting, target_id
    raise NotFoundError(f"Memory or fact {target_id!r} not found in the local index.")


@router.post("/memories/{memory_id}/hide", status_code=status.HTTP_204_NO_CONTENT)
def hide_memory(memory_id: str, session: SessionDep) -> None:
    target_type = "fact" if facts_repo.get_fact(session, memory_id) else "memory"
    overrides_repo.delete_overrides(session, target_id=memory_id, target_type=target_type)
    overrides_repo.create_override(
        session, target_type=target_type, target_id=memory_id, action="hidden", corrected_text=None
    )


@router.delete("/memories/{memory_id}/hide", status_code=status.HTTP_204_NO_CONTENT)
def unhide_memory(memory_id: str, session: SessionDep) -> None:
    overrides_repo.delete_overrides(session, target_id=memory_id)


@router.post(
    "/memories/{memory_id}/correct",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def correct_memory(
    memory_id: str,
    body: MemoryCorrectionRequest,
    background: BackgroundTasks,
    session: SessionDep,
    memory: MemoryDep,
    session_factory: FactoryDep,
) -> JobAccepted:
    if (body.scope_type is None) != (body.scope_id is None):
        raise ValidationError("scope_type and scope_id must be supplied together.")
    if body.scope_type is None or body.scope_id is None:
        scope_type, scope_id = _resolve_target(session, memory_id)
    else:
        scope_type, scope_id = body.scope_type, body.scope_id
    target_type = "fact" if facts_repo.get_fact(session, memory_id) else "memory"
    overrides_repo.delete_overrides(session, target_id=memory_id, target_type=target_type)
    overrides_repo.create_override(
        session,
        target_type=target_type,
        target_id=memory_id,
        action="corrected",
        corrected_text=body.corrected_text,
    )
    job = ingest_repo.create_job_row(session, "note")
    background.add_task(
        run_note_job,
        job.id,
        NoteRequest(text=body.corrected_text, scope_type=scope_type, scope_id=scope_id),
        memory=memory,
        session_factory=session_factory,
    )
    return JobAccepted(job_id=job.id)
