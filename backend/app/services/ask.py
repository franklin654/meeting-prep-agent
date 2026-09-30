"""Scoped Ask, pinned answers, and Remember this notes."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.core.errors import AppError, NotFoundError, ValidationError
from app.core.time import utcnow
from app.db import brief_repo, facts_repo, ingest_repo, overrides_repo, repository
from app.db.brief_repo import SessionFactory
from app.db.models import AskAnswer
from app.llm.client import LLMClient
from app.llm.prompt_loader import render_prompt
from app.memory.memory_service import MemoryService
from app.memory.tags import account_tag, contact_tag, meeting_tag
from app.schemas.ask import (
    UNGROUNDED_REPLY,
    AskRequest,
    AskResponse,
    NoteRequest,
    ReflectAnswer,
    SuggestedQuestions,
)
from app.schemas.brief import Citation, SourceType
from app.schemas.enums import ScopeType
from app.schemas.memory import MemoryHit
from app.schemas.reflect import parse_reflect_result
from app.services.brief import add_pinned_ask_answer, get_cached_brief
from app.services.evidence import QUOTE_MAX_CHARS, format_date, truncate

logger = logging.getLogger(__name__)


async def suggest_questions(
    meeting_id: str,
    *,
    llm: LLMClient,
    session_factory: SessionFactory,
) -> SuggestedQuestions:
    """Generate P4 suggestions from an existing cached memory brief only."""
    brief = await get_cached_brief(meeting_id, "memory", session_factory=session_factory)
    if brief is None:
        raise NotFoundError(f"No cached memory brief for meeting {meeting_id!r}.")
    with session_factory() as session:
        meeting = repository.get_meeting(session, meeting_id)
        if meeting is None:
            raise NotFoundError(f"Meeting {meeting_id!r} not found.")
        account = repository.get_account(session, meeting.account_id)
        if account is None:
            raise NotFoundError(f"Account {meeting.account_id!r} not found.")
        account_name = account.name
    prompt = render_prompt(
        "suggest_questions",
        account_name=account_name,
        brief_json=brief.model_dump_json(exclude={"generated_at"}),
    )
    result = await llm.complete_json(prompt, SuggestedQuestions, temperature=0.3)
    questions = [q.strip() for q in result.questions if q.strip()][:3]
    return SuggestedQuestions(questions=questions or ["What changed since the last meeting?"])


def _scope_tags(request: AskRequest, session_factory: SessionFactory) -> list[str]:
    with session_factory() as session:
        if request.scope_type == ScopeType.account:
            if repository.get_account(session, request.scope_id) is None:
                raise NotFoundError(f"Account {request.scope_id!r} not found.")
            return [account_tag(request.scope_id)]
        if request.scope_type == ScopeType.contact:
            if repository.get_contact(session, request.scope_id) is None:
                raise NotFoundError(f"Contact {request.scope_id!r} not found.")
            return [contact_tag(request.scope_id)]

        meeting = repository.get_meeting(session, request.scope_id)
        if meeting is None:
            raise NotFoundError(f"Meeting {request.scope_id!r} not found.")
        attendees = repository.list_attendees_for_meeting(session, meeting.id)
        return [
            account_tag(meeting.account_id),
            meeting_tag(meeting.id),
            *(contact_tag(attendee.contact_id) for attendee in attendees),
        ]


def _render_query(request: AskRequest) -> str:
    history = "\n".join(
        f"Q: {turn.question}\nA: {turn.answer}" for turn in request.history
    ) or "(none)"
    return render_prompt("reflect_answer", history=history, question=request.question)


def _citations(
    sources: list[MemoryHit], meeting_titles: dict[str, str]
) -> list[Citation]:
    citations: list[Citation] = []
    seen: set[tuple[str, str, str]] = set()
    for source in sources:
        if source.meeting_id is None or source.meeting_date is None:
            continue
        key = (source.meeting_id, source.memory_id, source.text)
        if key in seen:
            continue
        seen.add(key)
        citations.append(
            Citation(
                source_type=SourceType.meeting,
                meeting_id=source.meeting_id,
                meeting_date=source.meeting_date,
                label=(
                    f"{meeting_titles.get(source.meeting_id, 'Meeting')} · "
                    f"{format_date(source.meeting_date)}"
                ),
                quote=truncate(source.text, QUOTE_MAX_CHARS),
                memory_id=source.memory_id,
            )
        )
    return citations


async def ask_question(
    request: AskRequest,
    *,
    memory: MemoryService,
    session_factory: SessionFactory,
) -> AskResponse:
    tags = _scope_tags(request, session_factory)
    result = await memory.reflect_structured(
        query=_render_query(request),
        tags=tags,
        schema=ReflectAnswer,
        budget="mid",
    )
    parsed = parse_reflect_result("R5", result, ReflectAnswer)
    answer = parsed if isinstance(parsed, ReflectAnswer) else None

    source_rows = result.sources
    if answer and answer.confident:
        with session_factory() as session:
            hidden_memories = {
                row.target_id
                for row in overrides_repo.list_overrides(session, target_type="memory")
                if row.action in {"hidden", "corrected"}
            }
            hidden_fact_ids = {
                row.target_id
                for row in overrides_repo.list_overrides(session, target_type="fact")
                if row.action in {"hidden", "corrected"}
            }
            source_account_ids: set[str] = set()
            for source in source_rows:
                if source.meeting_id:
                    meeting = repository.get_meeting(session, source.meeting_id)
                    if meeting is not None:
                        source_account_ids.add(meeting.account_id)
            hidden_facts = [
                fact
                for account_id in source_account_ids
                for fact in facts_repo.list_account_facts(session, account_id)
                if fact.id in hidden_fact_ids
            ]
        source_rows = [
            source
            for source in source_rows
            if source.memory_id not in hidden_memories
            and not any(
                fact.meeting_id == source.meeting_id
                and (fact.text in source.text or fact.source_quote in source.text)
                for fact in hidden_facts
            )
        ]
    citations = await memory.resolve_sources(source_rows) if answer and answer.confident else []
    with session_factory() as session:
        meeting_titles = {
            meeting_id: meeting.title
            for meeting_id in {source.meeting_id for source in citations}
            if meeting_id is not None
            and (meeting := repository.get_meeting(session, meeting_id)) is not None
        }
    mapped = _citations(citations, meeting_titles)
    grounded = bool(answer and answer.confident and answer.answer.strip() and mapped)
    response = AskResponse(
        ask_answer_id=f"ask_{uuid.uuid4().hex[:8]}",
        answer=answer.answer.strip() if grounded and answer is not None else UNGROUNDED_REPLY,
        grounded=grounded,
        citations=mapped if grounded else [],
    )
    stored_answer = response.model_dump(mode="json")
    stored_answer.pop("ask_answer_id")
    row = AskAnswer(
        id=response.ask_answer_id,
        scope_type=request.scope_type,
        scope_id=request.scope_id,
        question=request.question,
        answer=stored_answer,
        created_at=utcnow(),
    )
    with session_factory() as session:
        repository.create_ask_answer(session, row)
    return response


async def pin_answer(
    ask_answer_id: str,
    meeting_id: str,
    *,
    session_factory: SessionFactory,
) -> AskResponse:
    with session_factory() as session:
        row = repository.get_ask_answer(session, ask_answer_id)
        if row is None:
            raise NotFoundError(f"AskAnswer {ask_answer_id!r} not found.")
        if repository.get_meeting(session, meeting_id) is None:
            raise NotFoundError(f"Meeting {meeting_id!r} not found.")
        response = AskResponse.model_validate({"ask_answer_id": row.id, **row.answer})
        if not response.grounded:
            raise ValidationError("Only grounded Ask answers can be pinned to a brief.")
        pinned = repository.pin_ask_answer(session, row.id, meeting_id=meeting_id)

    cached = brief_repo.get_fresh_brief(session_factory, meeting_id, "memory")
    if cached is not None:
        updated = add_pinned_ask_answer(cached, pinned)
        brief_repo.save_brief(session_factory, updated)
    return response


async def run_note_job(
    job_id: str,
    request: NoteRequest,
    *,
    memory: MemoryService,
    session_factory: SessionFactory,
) -> None:
    """Retain a note in the background and finish its polling job."""
    error: str | None = None
    result: dict[str, Any] | None = None
    try:
        await memory.retain_note(
            text=request.text,
            scope_type=request.scope_type,
            scope_id=request.scope_id,
        )
        result = {"facts": [], "new_commitments": 0, "closed_commitments": 0, "alerts": []}
    except AppError as exc:
        error = exc.code
    except Exception as exc:  # noqa: BLE001 - background job records failure and returns
        logger.error("ask.note_job_failed job=%s error_type=%s", job_id, type(exc).__name__)
        error = "internal_error"
    with session_factory() as session:
        ingest_repo.finish_job(session, job_id, result=result, error=error)
