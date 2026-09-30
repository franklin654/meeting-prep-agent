"""Memory inspector overview stays SQLite-backed and treats Hindsight stats as optional."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

import app.main as main_module
from app.api.deps import get_memory_service, get_session, get_session_factory
from app.db import overrides_repo
from app.db.facts_repo import replace_meeting_facts
from app.schemas.enums import FactKind
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
    def session_dependency() -> Iterator[Session]:
        with Session(world.engine) as session:
            yield session

    overrides = main_module.app.dependency_overrides
    overrides[get_session] = session_dependency
    overrides[get_session_factory] = lambda: world.session_factory
    overrides[get_memory_service] = lambda: memory
    yield TestClient(main_module.app)
    overrides.clear()


def test_overview_returns_visible_fact_counts_growth_hidden_items_and_optional_stats(
    client: TestClient, world: World, memory: FakeMemoryService
) -> None:
    with Session(world.engine) as session:
        facts = replace_meeting_facts(
            session,
            "m1_finedge",
            "acc_finedge",
            [
                ("c_rahul", FactKind.personal, "Rahul likes concise updates", "Concise updates."),
                ("c_rahul", FactKind.deal_fact, "The pilot is six weeks", "Six weeks."),
            ],
        )
        hidden_fact_id = facts[0].id
        overrides_repo.create_override(
            session,
            target_type="fact",
            target_id=hidden_fact_id,
            action="hidden",
            corrected_text=None,
        )

    response = client.get("/api/memory/overview")
    assert response.status_code == 200
    data = response.json()
    assert data["facts_by_kind"]["deal_fact"] >= 1
    assert data["facts_by_kind"].get("personal", 0) == 0
    fin_edge = next(row for row in data["growth"] if row["account_id"] == "acc_finedge")
    assert fin_edge["points"][-1]["fact_count"] == 1
    assert data["hidden_item_count"] == 1
    assert data["hidden_items"][0]["target_id"] == hidden_fact_id
    assert data["style_rules"]["notes"] == []
    assert data["hindsight_stats"] is None
    assert memory.reflect_calls == []


def test_overview_includes_read_only_bank_stats_when_available(
    client: TestClient, memory: FakeMemoryService
) -> None:
    memory.bank_stats = {
        "total_nodes": 31,
        "total_documents": 8,
        "nodes_by_fact_type": {"world": 28, "observation": 3},
        "total_observations": 3,
    }
    response = client.get("/api/memory/overview")
    assert response.status_code == 200
    assert response.json()["hindsight_stats"]["total_nodes"] == 31
