"""Reviewable transcript capture endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlmodel import Session

from app.api.deps import (
    get_llm_client_for_ingest,
    get_memory_service,
    get_session,
    get_session_factory,
)
from app.core.errors import NotFoundError, ValidationError
from app.db import capture_repo, ingest_repo, repository
from app.llm.client import LLMClient
from app.memory.memory_service import MemoryService
from app.schemas.api import CapturePreviewRequest, CaptureSaveRequest, JobAccepted
from app.services.capture import discard_capture, run_capture_preview, run_capture_save
from app.services.ingest import SessionFactory

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]
LlmDep = Annotated[LLMClient, Depends(get_llm_client_for_ingest)]
MemoryDep = Annotated[MemoryService, Depends(get_memory_service)]
SessionFactoryDep = Annotated[SessionFactory, Depends(get_session_factory)]


@router.post(
    "/meetings/{meeting_id}/capture/preview",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def preview_capture(
    meeting_id: str,
    body: CapturePreviewRequest,
    background: BackgroundTasks,
    session: SessionDep,
    llm: LlmDep,
    session_factory: SessionFactoryDep,
) -> JobAccepted:
    if repository.get_meeting(session, meeting_id) is None:
        raise NotFoundError(f"Meeting {meeting_id!r} not found.")
    job = ingest_repo.create_job_row(session, "capture_preview")
    background.add_task(
        run_capture_preview,
        job.id,
        meeting_id,
        body.transcript,
        llm=llm,
        session_factory=session_factory,
    )
    return JobAccepted(job_id=job.id)


@router.post(
    "/capture/{draft_id}/save",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def save_capture(
    draft_id: str,
    body: CaptureSaveRequest,
    background: BackgroundTasks,
    session: SessionDep,
    memory: MemoryDep,
    session_factory: SessionFactoryDep,
) -> JobAccepted:
    draft = capture_repo.get_draft(session, draft_id)
    if draft is None:
        raise NotFoundError(f"Capture draft {draft_id!r} not found.")
    existing_job_id = draft.extraction.get("save_job_id")
    if existing_job_id:
        return JobAccepted(job_id=str(existing_job_id))
    if draft.status != "open":
        raise ValidationError("Only an open capture draft can be saved.")
    known = {item.get("id") for item in draft.items}
    unknown = set(body.unchecked_item_ids) - known
    if unknown:
        raise ValidationError("unchecked_item_ids contains an unknown capture item.")
    job = ingest_repo.create_job_row(session, "capture_save")
    extraction = dict(draft.extraction)
    extraction["save_job_id"] = job.id
    capture_repo.update_draft(session, draft_id, status="open", extraction=extraction)
    background.add_task(
        run_capture_save,
        job.id,
        draft_id,
        set(body.unchecked_item_ids),
        memory=memory,
        session_factory=session_factory,
    )
    return JobAccepted(job_id=job.id)


@router.delete("/capture/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_capture(draft_id: str, session: SessionDep) -> None:
    discard_capture(session, draft_id)
