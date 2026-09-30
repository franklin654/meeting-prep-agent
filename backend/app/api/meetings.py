"""Meetings and notes endpoints (docs/technical-design.md "API routes"; ticket T13)."""

from __future__ import annotations

from datetime import UTC
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlmodel import Session

from app.api.deps import (
    get_llm_client_for_ingest,
    get_memory_service,
    get_session,
    get_session_factory,
)
from app.core.errors import NotFoundError, ValidationError
from app.core.time import today
from app.db import capture_repo, entities_repo, ingest_repo, meetings_repo, repository
from app.llm.client import LLMClient
from app.memory.memory_service import MemoryService
from app.schemas.api import ContactRef, JobAccepted, MeetingCreate, MeetingSummary, NotesRequest
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
    output: list[MeetingSummary] = []
    for row in meetings_repo.list_meeting_rows(session, status):
        followups, past, has_history = entities_repo.meeting_metrics(session, row.meeting)
        overdue = repository.list_overdue_commitments(session, account_id=row.meeting.account_id)
        output.append(
            MeetingSummary(
                id=row.meeting.id,
                account_id=row.meeting.account_id,
                account_name=row.account_name,
                title=row.meeting.title,
                scheduled_at=row.meeting.scheduled_at,
                status=row.meeting.status,
                attendees=[ContactRef(id=c.id, name=c.name, role=c.role) for c in row.attendees],
                brief_ready=row.brief_ready,
                prepared=capture_repo.is_prepared(session, row.meeting.id),
                open_followups=followups,
                past_meetings=past,
                has_history=has_history,
                overdue_followups=len(overdue),
                has_notes=bool(row.meeting.transcript and row.meeting.transcript.strip()),
            )
        )
    return output


@router.post("/meetings", response_model=MeetingSummary, status_code=status.HTTP_201_CREATED)
def schedule_meeting(body: MeetingCreate, session: SessionDep) -> MeetingSummary:
    scheduled = body.scheduled_at
    meeting_day = scheduled.date() if scheduled.tzinfo else scheduled.replace(tzinfo=UTC).date()
    if meeting_day < today():
        raise ValidationError("scheduled_at cannot be before the app's demo date.")
    meeting = entities_repo.create_meeting(
        session,
        account_id=body.account_id,
        title=body.title,
        scheduled_at=scheduled,
        attendee_ids=body.attendee_ids,
    )
    account = repository.get_account(session, meeting.account_id)
    assert account is not None
    attendees = entities_repo.attendees_for_meeting(session, meeting.id)
    return MeetingSummary(
        id=meeting.id,
        account_id=meeting.account_id,
        account_name=account.name,
        title=meeting.title,
        scheduled_at=meeting.scheduled_at,
        status=meeting.status,
        attendees=[ContactRef(id=c.id, name=c.name, role=c.role) for c in attendees],
        brief_ready=False,
        prepared=False,
        open_followups=0,
        past_meetings=0,
        has_history=False,
        overdue_followups=0,
        has_notes=False,
    )


@router.delete("/meetings/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meeting(meeting_id: str, session: SessionDep) -> None:
    entities_repo.cancel_meeting(session, meeting_id)


@router.post("/meetings/{meeting_id}/prepared", status_code=status.HTTP_204_NO_CONTENT)
def prepare_meeting(meeting_id: str, session: SessionDep) -> None:
    if repository.get_meeting(session, meeting_id) is None:
        raise NotFoundError(f"Meeting {meeting_id!r} not found.")
    capture_repo.mark_prepared(session, meeting_id)


@router.delete("/meetings/{meeting_id}/prepared", status_code=status.HTTP_204_NO_CONTENT)
def unprepare_meeting(meeting_id: str, session: SessionDep) -> None:
    if repository.get_meeting(session, meeting_id) is None:
        raise NotFoundError(f"Meeting {meeting_id!r} not found.")
    capture_repo.unmark_prepared(session, meeting_id)


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
