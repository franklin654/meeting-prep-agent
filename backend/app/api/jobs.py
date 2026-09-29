"""Job polling endpoint (docs/technical-design.md "API routes"; ticket T13)."""

from __future__ import annotations

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import get_session
from app.core.errors import NotFoundError
from app.db import repository
from app.schemas.api import CaptureDraftResponse, JobStatus, LearnedSummary

router = APIRouter()


@router.get("/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: str, session: Annotated[Session, Depends(get_session)]) -> JobStatus:
    """`pending`, `done` (with the learned summary) or `failed` (with the error code)."""
    job = repository.get_job(session, job_id)
    if job is None:
        raise NotFoundError(f"Job {job_id!r} not found.")
    learned = (
        LearnedSummary.model_validate(job.result)
        if job.status == "done" and job.result is not None and "facts" in job.result
        else None
    )
    draft = (
        CaptureDraftResponse.model_validate(job.result["draft"])
        if job.status == "done" and job.result is not None and "draft" in job.result
        else None
    )
    return JobStatus(
        id=job.id,
        kind=job.kind,
        status=cast(Literal["pending", "done", "failed"], job.status),
        learned=learned,
        draft=draft,
        error=job.error if job.status == "failed" else None,
    )
