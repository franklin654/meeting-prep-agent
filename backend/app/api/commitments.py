"""Contact follow-up controls."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlmodel import Session

from app.api.deps import get_session
from app.core.errors import NotFoundError
from app.db import repository
from app.schemas.api import CommitmentPatch, CommitmentResponse
from app.schemas.brief import Citation, SourceType

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


@router.patch("/commitments/{commitment_id}", response_model=CommitmentResponse)
def patch_commitment(
    commitment_id: str, body: CommitmentPatch, session: SessionDep
) -> CommitmentResponse:
    updated = repository.update_commitment(
        session,
        commitment_id,
        status=body.status,
        due_date=body.due_date,
        set_due_date="due_date" in body.model_fields_set,
        text=body.text,
    )
    meeting = repository.get_meeting(session, updated.meeting_id)
    if meeting is None:
        raise NotFoundError(f"Meeting {updated.meeting_id!r} not found.")
    day = meeting.scheduled_at.date()
    return CommitmentResponse(
        id=updated.id,
        owner=updated.owner,
        text=updated.text,
        due_date=updated.due_date,
        status=updated.status,
        meeting_id=updated.meeting_id,
        citation=Citation(
            source_type=SourceType.ledger,
            meeting_id=meeting.id,
            meeting_date=day,
            label=f"{meeting.title} · {day:%b} {day.day}",
            quote=updated.source_quote,
            memory_id=None,
        ),
    )


@router.delete("/commitments/{commitment_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_commitment(commitment_id: str, session: SessionDep) -> Response:
    repository.delete_commitment(session, commitment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
