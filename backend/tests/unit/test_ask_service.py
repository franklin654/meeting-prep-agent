"""Ask service tests: FakeMemoryService only, no live Hindsight calls."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from sqlmodel import Session

from app.core.time import utcnow
from app.db import brief_repo, ingest_repo, overrides_repo, repository
from app.db.models import AskAnswer
from app.schemas.ask import AskRequest, AskTurn, NoteRequest, ReflectAnswer, SuggestedQuestions
from app.schemas.brief import Brief, SectionKey
from app.schemas.enums import ScopeType
from app.schemas.memory import MemoryHit, ReflectResult
from app.services.ask import ask_question, pin_answer, run_note_job, suggest_questions
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fake_memory_service import FakeMemoryService
from tests.unit.brief_world import M6, World, make_world


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    yield from make_world(tmp_path)


def hit() -> MemoryHit:
    return MemoryHit(
        memory_id="ask-source-m2",
        text="Anita said the budget was about $40K.",
        meeting_id="m2_finedge",
        meeting_date=date(2026, 7, 28),
        tags=["account:acc_finedge", "contact:c_anita", "meeting:m2_finedge"],
    )


async def test_grounded_answer_uses_scope_history_and_citation(world: World) -> None:
    memory = FakeMemoryService()
    memory.queue_reflect_response(
        ReflectResult(
            text="budget answer",
            structured=ReflectAnswer(answer="About $40K.", confident=True).model_dump(),
            sources=[hit()],
            structured_error=None,
        )
    )

    response = await ask_question(
        AskRequest(
            question="What did Anita say about budget?",
            scope_type=ScopeType.contact,
            scope_id="c_anita",
            history=[AskTurn(question="Who is Anita?", answer="The CFO.")],
        ),
        memory=memory,
        session_factory=world.session_factory,
    )

    assert response.grounded and response.answer == "About $40K."
    assert response.citations[0].meeting_id == "m2_finedge"
    assert memory.reflect_calls[0][1] == ["contact:c_anita"]
    assert "Who is Anita?" in memory.reflect_calls[0][0]
    with Session(world.engine) as session:
        row = session.get(AskAnswer, response.ask_answer_id)
        assert row is not None and row.question == "What did Anita say about budget?"


async def test_ungrounded_answer_uses_fixed_reply_and_has_no_citations(world: World) -> None:
    memory = FakeMemoryService()
    memory.queue_reflect_response(
        ReflectResult(
            text="unsupported speculation",
            structured=ReflectAnswer(answer="Something guessed.", confident=True).model_dump(),
            sources=[],
            structured_error=None,
        )
    )

    response = await ask_question(
        AskRequest(
            question="What is Rahul's favourite food?",
            scope_type=ScopeType.account,
            scope_id="acc_finedge",
        ),
        memory=memory,
        session_factory=world.session_factory,
    )

    assert not response.grounded
    assert response.answer == "Nothing in memory covers that yet."
    assert response.citations == []


async def test_hidden_memory_source_cannot_ground_an_ask_answer(world: World) -> None:
    memory = FakeMemoryService()
    memory.queue_reflect_response(
        ReflectResult(
            text="grounded only by the hidden source",
            structured=ReflectAnswer(answer="About $40K.", confident=True).model_dump(),
            sources=[hit()],
            structured_error=None,
        )
    )
    with Session(world.engine) as session:
        overrides_repo.create_override(
            session,
            target_type="memory",
            target_id="ask-source-m2",
            action="hidden",
            corrected_text=None,
        )

    response = await ask_question(
        AskRequest(
            question="What did Anita say about budget?",
            scope_type=ScopeType.contact,
            scope_id="c_anita",
        ),
        memory=memory,
        session_factory=world.session_factory,
    )

    assert not response.grounded
    assert response.answer == "Nothing in memory covers that yet."
    assert response.citations == []


async def test_meeting_scope_expands_account_and_attendee_tags(world: World) -> None:
    memory = FakeMemoryService()
    memory.queue_reflect_response(
        ReflectResult(
            text="empty",
            structured=ReflectAnswer(answer="", confident=False).model_dump(),
            sources=[],
            structured_error=None,
        )
    )

    await ask_question(
        AskRequest(question="Any context?", scope_type=ScopeType.meeting, scope_id=M6),
        memory=memory,
        session_factory=world.session_factory,
    )

    tags = memory.reflect_calls[0][1]
    assert "account:acc_finedge" in tags
    assert "meeting:m6_finedge" in tags
    assert "contact:c_anita" in tags and "contact:c_karan" in tags


async def test_pin_adds_grounded_answer_to_cached_your_questions_section(world: World) -> None:
    memory = FakeMemoryService()
    memory.queue_reflect_response(
        ReflectResult(
            text="budget answer",
            structured=ReflectAnswer(answer="About $40K.", confident=True).model_dump(),
            sources=[hit()],
            structured_error=None,
        )
    )
    response = await ask_question(
        AskRequest(
            question="What did Anita say about budget?",
            scope_type=ScopeType.account,
            scope_id="acc_finedge",
        ),
        memory=memory,
        session_factory=world.session_factory,
    )
    cached = Brief(
        id="br_ask_test",
        meeting_id=M6,
        mode="memory",
        generated_at=utcnow(),
        sections=[],
        facts_used=0,
        preferences_applied=[],
    )
    brief_repo.save_brief(world.session_factory, cached)

    pinned = await pin_answer(
        response.ask_answer_id,
        M6,
        session_factory=world.session_factory,
    )

    assert pinned.ask_answer_id == response.ask_answer_id
    updated = brief_repo.get_fresh_brief(world.session_factory, M6, "memory")
    assert updated is not None
    section = next(s for s in updated.sections if s.key == SectionKey.your_questions)
    assert section.items[0].text == "Q: What did Anita say about budget?\nA: About $40K."
    assert section.items[0].citations[0].meeting_id == "m2_finedge"


async def test_remember_this_retains_scoped_note_and_finishes_job(world: World) -> None:
    memory = FakeMemoryService()
    request = NoteRequest(
        text="Anita prefers budget updates in a short email.",
        scope_type=ScopeType.contact,
        scope_id="c_anita",
    )
    with Session(world.engine) as session:
        job = ingest_repo.create_job_row(session, "note")

    await run_note_job(job.id, request, memory=memory, session_factory=world.session_factory)

    assert memory.items[0].text == request.text
    assert "kind:note" in memory.items[0].tags and "contact:c_anita" in memory.items[0].tags
    with Session(world.engine) as session:
        saved_job = repository.get_job(session, job.id)
        assert saved_job is not None and saved_job.status == "done"


async def test_p4_suggestions_use_only_cached_brief_and_fake_llm(world: World) -> None:
    cached = Brief(
        id="br_p4",
        meeting_id=M6,
        mode="memory",
        generated_at=utcnow(),
        sections=[],
        facts_used=0,
        preferences_applied=[],
    )
    brief_repo.save_brief(world.session_factory, cached)
    fake = FakeLLM()
    fake.queue_response(
        SuggestedQuestions(
            questions=["What changed in the budget?", "Who owns the deck?", "Any objections?"]
        )
    )

    result = await suggest_questions(M6, llm=fake, session_factory=world.session_factory)

    assert len(fake.calls) == 1 and fake.calls[0].schema is SuggestedQuestions
    assert "FinEdge Payments" in fake.calls[0].prompt
    assert len(result.questions) == 3
