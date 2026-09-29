"""Meetings and notes endpoints (docs/technical-design.md "API routes"; ticket T13)."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlmodel import Session

from app.api.deps import (
    get_llm_client_for_ingest,
    get_memory_service,
    get_session,
    get_session_factory,
)
from app.db import ingest_repo, meetings_repo
from app.llm.client import LLMClient
from app.memory.memory_service import MemoryService
from app.schemas.api import ContactRef, JobAccepted, MeetingSummary, NotesRequest
from app.services.ingest import SessionFactory, run_ingest_job

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]
LlmDep = Annotated[LLMClient, Depends(get_llm_client_for_ingest)]
MemoryDep = Annotated[MemoryService, Depends(get_memory_service)]
SessionFactoryDep = Annotated[SessionFactory, Depends(get_session_factory)]


@router.get("/meetings", response_model=list[MeetingSummary])
def list_meetings(
    session: SessionDep,
    status: Literal["upcoming", "done"] | None = None,
) -> list[MeetingSummary]:
    """Meetings with attendees and brief status, soonest first."""
    return [
        MeetingSummary(
            id=row.meeting.id,
            account_id=row.meeting.account_id,
            account_name=row.account_name,
            title=row.meeting.title,
            scheduled_at=row.meeting.scheduled_at,
            status=row.meeting.status,
            attendees=[ContactRef(id=c.id, name=c.name, role=c.role) for c in row.attendees],
            brief_ready=row.brief_ready,
        )
        for row in meetings_repo.list_meeting_rows(session, status)
    ]


@router.post(
    "/meetings/{meeting_id}/notes",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_notes(
    meeting_id: str,
    body: NotesRequest,
    background: BackgroundTasks,
    session: SessionDep,
    llm: LlmDep,
    memory: MemoryDep,
    session_factory: SessionFactoryDep,
) -> JobAccepted:
    """Save the transcript, create an ingest job and run ingest after the response.

    The background task gets `session_factory`, not the request session, which is
    closed when the request ends. The meeting is marked done by ingest itself.
    """
    meetings_repo.save_transcript(session, meeting_id, body.transcript)
    job = ingest_repo.create_job_row(session, "ingest")
    background.add_task(
        run_ingest_job,
        job.id,
        meeting_id,
        llm=llm,
        memory=memory,
        session_factory=session_factory,
    )
    return JobAccepted(job_id=job.id)
