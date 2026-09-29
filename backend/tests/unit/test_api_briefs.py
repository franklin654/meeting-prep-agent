"""T15: brief API (POST regenerates, GET reads the cache), fakes only, no network."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

import app.api.briefs as briefs_module
import app.api.deps as deps
import app.db.session as db_session
import app.main as main_module
from app.api.deps import get_brief_llm, get_memory_service, get_session, get_session_factory
from app.core.errors import (
    AppError,
    LLMInvalidOutputError,
    LLMTimeoutError,
    MemoryUnavailableError,
    RateLimitedError,
)
from app.db.models import Meeting
from app.schemas.brief import Brief
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fake_memory_service import FakeMemoryService
from tests.unit.brief_world import (
    M6,
    ScriptedLLM,
    World,
    good_draft,
    make_world,
    queue_objections,
)
from tests.unit.test_api_meetings_jobs import _settings

URL = f"/api/meetings/{M6}/brief"


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    yield from make_world(tmp_path)


@pytest.fixture
def llm() -> ScriptedLLM:
    return ScriptedLLM(good_draft)


def _install(world: World, llm: FakeLLM, memory: FakeMemoryService | None = None) -> TestClient:
    def _session() -> Iterator[Session]:
        with Session(world.engine) as s:
            yield s

    overrides = main_module.app.dependency_overrides
    overrides[get_session] = _session
    overrides[get_session_factory] = lambda: world.session_factory
    overrides[get_brief_llm] = lambda: llm
    overrides[get_memory_service] = lambda: memory or world.memory
    return TestClient(main_module.app)


@pytest.fixture
def client(world: World, llm: ScriptedLLM) -> Iterator[TestClient]:
    yield _install(world, llm)
    main_module.app.dependency_overrides.clear()


def _brief(response: Any) -> Brief:
    assert response.status_code == 200, response.text
    return Brief.model_validate(response.json())


def test_post_memory_default_every_item_cited(client: TestClient) -> None:
    brief = _brief(client.post(URL))
    assert brief.mode == "memory"
    assert brief.meeting_id == M6
    items = [i for s in brief.sections for i in s.items]
    assert items
    for it in items:
        assert it.citations
        for c in it.citations:
            assert c.meeting_id and c.meeting_date and c.quote


def test_post_no_memory_zero_citations_zero_memory_calls(client: TestClient, world: World) -> None:
    brief = _brief(client.post(URL, params={"mode": "no_memory"}))
    assert brief.mode == "no_memory"
    assert all(not i.citations for s in brief.sections for i in s.items)
    assert world.memory.get_memory_calls == []
    assert world.memory.reflect_calls == []


def test_get_404_before_post_then_same_brief_after(client: TestClient) -> None:
    first = client.get(URL)
    assert first.status_code == 404
    assert first.json()["error"]["code"] == "not_found"

    posted = _brief(client.post(URL))
    assert _brief(client.get(URL)) == posted
    assert client.get(URL, params={"mode": "no_memory"}).status_code == 404


def test_stale_cache_404_and_post_regenerates_same_id(client: TestClient, world: World) -> None:
    posted = _brief(client.post(URL))
    with Session(world.engine) as s:
        meeting = s.get(Meeting, "m5_finedge")
        assert meeting is not None
        meeting.ingested_at = datetime.now(UTC) + timedelta(hours=1)
        s.add(meeting)
        s.commit()

    assert client.get(URL).status_code == 404

    queue_objections(world.memory)
    again = _brief(client.post(URL))
    assert again.id == posted.id
    assert again.generated_at > posted.generated_at


def test_post_always_regenerates_even_when_cached(
    client: TestClient, llm: ScriptedLLM, world: World
) -> None:
    _brief(client.post(URL))
    queue_objections(world.memory)
    _brief(client.post(URL))
    assert len(llm.calls) == 2


@pytest.mark.parametrize("method", ["get", "post"])
def test_unknown_meeting_404(client: TestClient, method: str) -> None:
    response = getattr(client, method)("/api/meetings/nope/brief")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("method", ["get", "post"])
def test_bad_mode_422(client: TestClient, method: str) -> None:
    response = getattr(client, method)(URL, params={"mode": "bogus"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


class BrokenMemory(FakeMemoryService):
    async def recall_facts(
        self,
        *,
        query: str,
        tags: Sequence[str],
        fact_kind: Any = None,
        timeout_s: float | None = None,
    ) -> Any:
        raise MemoryUnavailableError("down")

    async def reflect_structured(self, **kwargs: Any) -> Any:
        raise MemoryUnavailableError("down")

    async def get_mental_model(self, name: str) -> Any:
        raise MemoryUnavailableError("down")


def test_memory_unavailable_503(world: World, llm: ScriptedLLM) -> None:
    client = _install(world, llm, BrokenMemory())
    try:
        response = client.post(URL)
    finally:
        main_module.app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "memory_unavailable"
    assert llm.calls == []


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (LLMTimeoutError("slow"), 504, "llm_timeout"),
        (LLMInvalidOutputError("bad"), 502, "llm_invalid_output"),
        (RateLimitedError("limit"), 429, "rate_limited"),
    ],
)
def test_llm_errors_map_to_status(world: World, error: AppError, status: int, code: str) -> None:
    fake = FakeLLM()
    fake.queue_error(error)
    client = _install(world, fake)
    try:
        response = client.post(URL)
    finally:
        main_module.app.dependency_overrides.clear()
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_empty_memory_brief_is_200_with_warning(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def empty(meeting_id: str, mode: str, **_: Any) -> Brief:
        return Brief(
            id="br_x",
            meeting_id=meeting_id,
            mode="memory",
            generated_at=datetime(2026, 9, 1, tzinfo=UTC),
            sections=[],
            facts_used=0,
            preferences_applied=[],
        )

    monkeypatch.setattr(briefs_module, "generate_brief", empty)
    with caplog.at_level(logging.WARNING):
        response = client.post(URL)
    assert response.status_code == 200
    assert response.json()["sections"] == []
    assert any("brief.empty" in r.getMessage() for r in caplog.records)


def test_request_logs_one_line_without_content(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.api.briefs"):
        _brief(client.post(URL))
    lines = [r.getMessage() for r in caplog.records if r.name == "app.api.briefs"]
    assert len(lines) == 1
    assert M6 in lines[0] and "mode=memory" in lines[0] and "duration=" in lines[0]
    assert "Pilot scoping" not in lines[0]


def test_openapi_paths_and_response_model(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    path = spec["paths"]["/api/meetings/{meeting_id}/brief"]
    assert set(path) == {"get", "post"}
    for verb in ("get", "post"):
        ref = path[verb]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        assert ref.endswith("/Brief")
    assert set(spec["components"]["schemas"]["Brief"]["properties"]) == set(Brief.model_fields)


def test_responds_within_budget_with_instant_fakes(client: TestClient) -> None:
    start = time.monotonic()
    _brief(client.post(URL))
    assert time.monotonic() - start < 2.0


def test_meetings_list_brief_ready_unchanged(client: TestClient) -> None:
    def ready() -> dict[str, bool]:
        return {r["id"]: r["brief_ready"] for r in client.get("/api/meetings").json()}

    assert ready()[M6] is False
    _brief(client.post(URL))
    assert ready()[M6] is True  # existing T13 rule: a stored brief record means ready


def test_startup_does_not_build_memory_or_llm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 's.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    built: list[str] = []

    class Boom:
        def __init__(self) -> None:
            built.append("memory")
            raise AssertionError("no memory at startup")

    def boom_llm() -> Any:
        built.append("llm")
        raise AssertionError("no llm at startup")

    monkeypatch.setattr(deps, "HindsightMemoryService", Boom)
    monkeypatch.setattr(deps, "_memory", None)
    monkeypatch.setattr(deps, "_brief_llm", None)
    monkeypatch.setattr(deps, "default_brief_llm", boom_llm)
    monkeypatch.setattr(main_module, "settings", _settings())
    monkeypatch.setattr(db_session, "engine", engine)
    with TestClient(main_module.app) as started:
        assert started.get("/api/health").json() == {
            "status": "ok",
            "demo_today": "2026-09-28",
            "ae_name": "Priya Nair",
            "company_name": "Tracewise",
        }
    assert built == []
    engine.dispose()


def test_get_brief_llm_is_built_lazily_once(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = FakeLLM()
    calls: list[int] = []

    def build() -> FakeLLM:
        calls.append(1)
        return sentinel

    monkeypatch.setattr(deps, "_brief_llm", None)
    monkeypatch.setattr(deps, "default_brief_llm", build)
    assert deps.get_brief_llm() is sentinel
    assert deps.get_brief_llm() is sentinel
    assert calls == [1]
