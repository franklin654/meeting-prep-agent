"""B4 contact profile controls and explicit pattern refresh; no live services."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

import app.main as main_module
from app.api.deps import get_brief_llm, get_memory_service, get_session, get_session_factory
from app.db import overrides_repo
from app.db.facts_repo import replace_meeting_facts
from app.schemas.enums import FactKind
from app.schemas.patterns import ContactPatternDraft, ContactPatternSuggestion
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fake_memory_service import FakeMemoryService
from tests.unit.brief_world import World, make_world


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    yield from make_world(tmp_path)


@pytest.fixture
def llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def memory() -> FakeMemoryService:
    return FakeMemoryService()


@pytest.fixture
def client(world: World, llm: FakeLLM, memory: FakeMemoryService) -> Iterator[TestClient]:
    def session_dependency() -> Iterator[Session]:
        with Session(world.engine) as session:
            yield session

    overrides = main_module.app.dependency_overrides
    overrides[get_session] = session_dependency
    overrides[get_session_factory] = lambda: world.session_factory
    overrides[get_brief_llm] = lambda: llm
    overrides[get_memory_service] = lambda: memory
    yield TestClient(main_module.app)
    overrides.clear()


def add_rahul_facts(world: World, count: int = 3) -> list[str]:
    rows = [
        (
            "c_rahul",
            FactKind.deal_fact,
            f"Rahul fact {index} about the pilot",
            f"Rahul said pilot fact {index}",
        )
        for index in range(count)
    ]
    with Session(world.engine) as session:
        facts = replace_meeting_facts(session, "m3_finedge", "acc_finedge", rows)
    return [fact.id for fact in facts]


def test_profile_groups_sqlite_facts_and_followups(client: TestClient, world: World) -> None:
    add_rahul_facts(world, 2)

    response = client.get("/api/contacts/c_rahul/profile")

    assert response.status_code == 200, response.text
    profile = response.json()
    assert profile["contact"]["name"] == "Rahul Mehta"
    assert profile["account"]["name"] == "FinEdge Payments"
    assert profile["stats"]["facts"] == 2
    assert profile["stats"]["open_follow_ups"] == 1
    assert any(row["title"] == "Technical deep dive" for row in profile["timeline"])
    assert any(item["kind"] == "commitment" for row in profile["timeline"] for item in row["items"])
    assert profile["follow_ups"][0]["id"] == "cm_deck"


def test_hide_and_unhide_fact_updates_profile(client: TestClient, world: World) -> None:
    fact_id = add_rahul_facts(world, 1)[0]

    hidden = client.post(f"/api/memories/{fact_id}/hide")
    hidden_profile = client.get("/api/contacts/c_rahul/profile").json()
    unhidden = client.delete(f"/api/memories/{fact_id}/hide")
    visible_profile = client.get("/api/contacts/c_rahul/profile").json()

    assert hidden.status_code == 204
    assert hidden_profile["hidden_count"] == 1
    assert hidden_profile["stats"]["facts"] == 0
    assert unhidden.status_code == 204
    assert visible_profile["hidden_count"] == 0
    assert visible_profile["stats"]["facts"] == 1


def test_correct_hides_original_and_uses_existing_note_retain_path(
    client: TestClient,
    world: World,
    memory: FakeMemoryService,
) -> None:
    fact_id = add_rahul_facts(world, 1)[0]

    response = client.post(
        f"/api/memories/{fact_id}/correct",
        json={"corrected_text": "Rahul prefers a shorter technical review."},
    )

    assert response.status_code == 202, response.text
    assert memory.items[-1].text == "Rahul prefers a shorter technical review."
    assert memory.items[-1].tags
    profile = client.get("/api/contacts/c_rahul/profile").json()
    assert profile["stats"]["facts"] == 0
    assert profile["hidden_count"] == 1
    with Session(world.engine) as session:
        override = next(
            row for row in overrides_repo.list_overrides(session) if row.target_id == fact_id
        )
        assert override is not None and override.action == "corrected"


def test_commitment_patch_and_delete(client: TestClient) -> None:
    patched = client.patch(
        "/api/commitments/cm_deck",
        json={"text": "Send updated pricing deck", "due_date": "2026-10-05"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["text"] == "Send updated pricing deck"
    assert patched.json()["due_date"] == "2026-10-05"
    assert client.delete("/api/commitments/cm_deck").status_code == 204


def test_pattern_refresh_uses_one_call_and_drops_invalid_citations(
    client: TestClient, world: World, llm: FakeLLM
) -> None:
    fact_ids = add_rahul_facts(world, 3)
    llm.queue_response(
        ContactPatternDraft(
            patterns=[
                ContactPatternSuggestion(
                    text="Rahul likes concise technical reviews", fact_ids=[fact_ids[0], "invalid"]
                ),
                ContactPatternSuggestion(text="Uncited claim", fact_ids=["invalid-only"]),
            ]
        )
    )

    response = client.post("/api/contacts/c_rahul/patterns/refresh")

    assert response.status_code == 200, response.text
    assert len(llm.calls) == 1
    assert len(llm.calls[0].prompt) < 5000
    assert response.json()[0]["text"] == "Rahul likes concise technical reviews"
    assert response.json()[0]["citations"][0]["meeting_id"] == "m3_finedge"
    assert client.get("/api/contacts/c_rahul/profile").json()["patterns"] == response.json()


def test_pattern_refresh_below_three_facts_makes_no_llm_call(
    client: TestClient, llm: FakeLLM
) -> None:
    response = client.post("/api/contacts/c_rahul/patterns/refresh")

    assert response.status_code == 200
    assert response.json() == []
    assert llm.calls == []
