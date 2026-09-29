"""T23 Ask endpoints with FakeMemoryService only."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

import app.main as main_module
from app.api.deps import get_memory_service, get_session, get_session_factory
from app.schemas.ask import ReflectAnswer
from app.schemas.memory import MemoryHit, ReflectResult
from tests.fakes.fake_memory_service import FakeMemoryService
from tests.unit.brief_world import World, make_world


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    yield from make_world(tmp_path)


@pytest.fixture
def memory() -> FakeMemoryService:
    return FakeMemoryService()


@pytest.fixture
def client(world: World, memory: FakeMemoryService) -> Iterator[TestClient]:
    def get_test_session() -> Iterator[Session]:
        with Session(world.engine) as session:
            yield session

    overrides = main_module.app.dependency_overrides
    overrides[get_session] = get_test_session
    overrides[get_session_factory] = lambda: world.session_factory
    overrides[get_memory_service] = lambda: memory
    yield TestClient(main_module.app)
    overrides.clear()


def test_post_ask_returns_grounded_answer_with_citation(
    client: TestClient, memory: FakeMemoryService
) -> None:
    memory.queue_reflect_response(
        ReflectResult(
            text="grounded",
            structured=ReflectAnswer(answer="About $40K.", confident=True).model_dump(),
            sources=[
                MemoryHit(
                    memory_id="source-m2",
                    text="Anita said the budget was about $40K.",
                    meeting_id="m2_finedge",
                    meeting_date=date(2026, 7, 28),
                    tags=[],
                )
            ],
            structured_error=None,
        )
    )

    response = client.post(
        "/api/ask",
        json={
            "question": "What did Anita say about budget?",
            "scope_type": "account",
            "scope_id": "acc_finedge",
        },
    )

    assert response.status_code == 200
    assert response.json()["grounded"] is True
    assert response.json()["citations"][0]["meeting_id"] == "m2_finedge"


def test_post_note_returns_job_and_retains_note(
    client: TestClient, memory: FakeMemoryService
) -> None:
    response = client.post(
        "/api/memories/notes",
        json={
            "text": "Anita prefers budget updates by email.",
            "scope_type": "contact",
            "scope_id": "c_anita",
        },
    )

    assert response.status_code == 202
    assert memory.items[-1].text == "Anita prefers budget updates by email."
    assert "kind:note" in memory.items[-1].tags
