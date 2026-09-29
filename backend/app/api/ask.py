"""Ask, pin, and Remember this endpoints (T23)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlmodel import Session

from app.api.deps import get_brief_llm, get_memory_service, get_session, get_session_factory
from app.db import ingest_repo
from app.llm.client import LLMClient
from app.memory.memory_service import MemoryService
from app.schemas.api import JobAccepted
from app.schemas.ask import AskRequest, AskResponse, NoteRequest, PinRequest, SuggestedQuestions
from app.services.ask import ask_question, pin_answer, run_note_job, suggest_questions
from app.services.ingest import SessionFactory

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]
MemoryDep = Annotated[MemoryService, Depends(get_memory_service)]
SessionFactoryDep = Annotated[SessionFactory, Depends(get_session_factory)]
LlmDep = Annotated[LLMClient, Depends(get_brief_llm)]


@router.get("/meetings/{meeting_id}/suggested-questions", response_model=SuggestedQuestions)
async def get_suggested_questions(
    meeting_id: str,
    llm: LlmDep,
    session_factory: SessionFactoryDep,
) -> SuggestedQuestions:
    return await suggest_questions(meeting_id, llm=llm, session_factory=session_factory)


@router.post("/ask", response_model=AskResponse)
async def post_ask(
    body: AskRequest,
    memory: MemoryDep,
    session_factory: SessionFactoryDep,
) -> AskResponse:
    return await ask_question(body, memory=memory, session_factory=session_factory)


@router.post("/ask/{ask_answer_id}/pin", response_model=AskResponse)
async def post_pin(
    ask_answer_id: str,
    body: PinRequest,
    session_factory: SessionFactoryDep,
) -> AskResponse:
    return await pin_answer(
        ask_answer_id,
        body.meeting_id,
        session_factory=session_factory,
    )


@router.post(
    "/memories/notes",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def post_note(
    body: NoteRequest,
    background: BackgroundTasks,
    session: SessionDep,
    memory: MemoryDep,
    session_factory: SessionFactoryDep,
) -> JobAccepted:
    job = ingest_repo.create_job_row(session, "note")
    background.add_task(
        run_note_job,
        job.id,
        body,
        memory=memory,
        session_factory=session_factory,
    )
    return JobAccepted(job_id=job.id)
