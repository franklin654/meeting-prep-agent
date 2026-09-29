"""T13: meetings, notes and jobs API, with dependency overrides (no network, no Hindsight)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

import app.api.deps as deps
import app.db.session as db_session
import app.main as main_module
from app.api.deps import (
    get_llm_client_for_ingest,
    get_memory_service,
    get_session,
    get_session_factory,
)
from app.config import Settings
from app.core.errors import LLMTimeoutError
from app.db import repository as repo
from app.db.models import Account, BriefRecord, Contact, Meeting
from app.schemas.api import JobAccepted, JobStatus, LearnedSummary, MeetingSummary, NotesRequest
from app.schemas.extraction import MeetingExtraction
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fake_memory_service import FakeMemoryService

ROOT = Path(__file__).resolve().parents[3]
TRANSCRIPTS = ROOT / "data" / "seed" / "transcripts"
FIXTURES = Path(__file__).parent / "fixtures"
LONG_NOTE = "Priya and Karan met to discuss the pilot rollout, budget and security review."


def _empty_extraction() -> MeetingExtraction:
    return MeetingExtraction(
        people=[], commitments=[], acknowledgements=[], facts=[], deal_budget_usd=None
    )


class SlowLLM(FakeLLM):
    """Sleeps before answering, to prove the POST response does not wait on ingest."""

    async def complete_json(self, prompt: str, schema: type[Any], **kwargs: Any) -> Any:
        await asyncio.sleep(1.0)
        return await super().complete_json(prompt, schema, **kwargs)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    eng = create_engine(
        f"sqlite:///{tmp_path / 'api.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def memory() -> FakeMemoryService:
    return FakeMemoryService()


@pytest.fixture
def seeded(engine: Engine) -> None:
    with Session(engine) as db:
        repo.create_account(
            db, Account(id="acc_finedge", name="FinEdge Payments", industry="fintech", stage="eval")
        )
        repo.create_account(
            db, Account(id="acc_other", name="Other Co", industry="retail", stage="eval")
        )
        for cid, name, role, acct in [
            ("c_priya", "Priya Nair", "Account Executive", None),
            ("c_arjun", "Arjun Menon", "Sales Engineer", None),
            ("c_rahul", "Rahul Mehta", "VP Engineering", "acc_finedge"),
            ("c_karan", "Karan Shah", None, "acc_finedge"),
        ]:
            repo.create_contact(db, Contact(id=cid, account_id=acct, name=name, role=role))
        for mid, acct, day, title, status, who in [
            ("m_late", "acc_other", 20, "Later", "upcoming", []),
            ("m4_finedge", "acc_finedge", 5, "Pilot scoping", "upcoming", ["c_rahul", "c_karan"]),
            ("m_old", "acc_other", 1, "Old", "done", []),
            ("m6_finedge", "acc_finedge", 10, "Pilot decision", "upcoming", ["c_priya", "c_rahul"]),
        ]:
            repo.create_meeting(
                db,
                Meeting(
                    id=mid,
                    account_id=acct,
                    title=title,
                    scheduled_at=datetime(2026, 9, day, 10, tzinfo=UTC),
                    status=status,
                ),
            )
            for cid in who:
                repo.add_attendee(db, mid, cid)
        repo.create_brief_record(
            db,
            BriefRecord(
                id="br_1",
                meeting_id="m6_finedge",
                mode="no_memory",
                content={},
                created_at=datetime(2026, 9, 1, tzinfo=UTC),
            ),
        )


@pytest.fixture
def client(
    engine: Engine, seeded: None, llm: FakeLLM, memory: FakeMemoryService
) -> Iterator[TestClient]:
    def _session() -> Iterator[Session]:
        with Session(engine) as s:
            yield s

    overrides = main_module.app.dependency_overrides
    overrides[get_session] = _session
    overrides[get_session_factory] = lambda: lambda: Session(engine)
    overrides[get_llm_client_for_ingest] = lambda: llm
    overrides[get_memory_service] = lambda: memory
    yield TestClient(main_module.app)
    overrides.clear()


def _job(client: TestClient, job_id: str) -> JobStatus:
    response = client.get(f"/api/jobs/{job_id}")
    assert response.status_code == 200
    return JobStatus.model_validate(response.json())


def _meeting(engine: Engine, meeting_id: str) -> Meeting:
    with Session(engine) as db:
        meeting = repo.get_meeting(db, meeting_id)
        assert meeting is not None
        db.expunge(meeting)
        return meeting


# ---- GET /api/meetings ----


def test_list_meetings_sorted_with_attendees_and_brief_ready(client: TestClient) -> None:
    response = client.get("/api/meetings")
    assert response.status_code == 200
    rows = [MeetingSummary.model_validate(r) for r in response.json()]
    assert [r.id for r in rows] == ["m_old", "m4_finedge", "m6_finedge", "m_late"]
    by_id = {r.id: r for r in rows}
    m6 = by_id["m6_finedge"]
    assert m6.account_name == "FinEdge Payments" and m6.account_id == "acc_finedge"
    assert [(a.id, a.name, a.role) for a in m6.attendees] == [
        ("c_priya", "Priya Nair", "Account Executive"),
        ("c_rahul", "Rahul Mehta", "VP Engineering"),
    ]
    assert by_id["m4_finedge"].attendees[0].role is None
    assert m6.brief_ready is False  # B18: only a fresh memory brief counts; this one is no_memory
    assert by_id["m4_finedge"].brief_ready is False
    assert by_id["m_old"].attendees == []
    assert by_id["m6_finedge"].has_history is False


def test_entity_and_schedule_endpoints(client: TestClient) -> None:
    account = client.post("/api/accounts", json={"name": "New account"})
    assert account.status_code == 200
    account_body = account.json()
    assert account_body["id"].startswith("acc_")
    assert account_body["stage"] == "discovery"
    contact = client.post(
        "/api/contacts", json={"account_id": account_body["id"], "name": "New contact"}
    )
    assert contact.status_code == 200
    contact_body = contact.json()
    assert contact_body["id"].startswith("c_")
    listing = client.get("/api/contacts", params={"query": "New", "account_id": account_body["id"]})
    assert listing.json()[0]["meetings_count"] == 0
    scheduled = client.post(
        "/api/meetings",
        json={
            "account_id": account_body["id"],
            "title": "First call",
            "scheduled_at": "2026-09-28T10:00:00Z",
            "attendee_ids": [contact_body["id"]],
        },
    )
    assert scheduled.status_code == 201
    meeting = scheduled.json()
    assert meeting["id"].startswith("m_")
    assert meeting["status"] == "upcoming"
    assert meeting["has_history"] is False
    assert client.post(f"/api/meetings/{meeting['id']}/prepared").status_code == 204
    assert client.get("/api/meetings").json()[-1]["prepared"] is True
    assert client.delete(f"/api/meetings/{meeting['id']}/prepared").status_code == 204
    assert client.delete(f"/api/meetings/{meeting['id']}").status_code == 204
    assert client.delete(f"/api/meetings/{meeting['id']}").status_code == 404


def test_schedule_rejects_wrong_account_contact_and_past_day(client: TestClient) -> None:
    response = client.post(
        "/api/meetings",
        json={
            "account_id": "acc_finedge",
            "title": "Bad attendees",
            "scheduled_at": "2026-09-28T10:00:00Z",
            "attendee_ids": ["missing"],
        },
    )
    assert response.status_code == 422
    wrong_vendor_contact = client.post(
        "/api/meetings",
        json={
            "account_id": "acc_finedge",
            "title": "Wrong Tracewise attendee",
            "scheduled_at": "2026-09-28T10:00:00Z",
            "attendee_ids": ["c_arjun"],
        },
    )
    assert wrong_vendor_contact.status_code == 422
    past = client.post(
        "/api/meetings",
        json={"account_id": "acc_finedge", "title": "Past", "scheduled_at": "2026-09-27T10:00:00Z"},
    )
    assert past.status_code == 422


def test_list_meetings_status_filter(client: TestClient) -> None:
    upcoming = client.get("/api/meetings", params={"status": "upcoming"}).json()
    assert [r["id"] for r in upcoming] == ["m4_finedge", "m6_finedge", "m_late"]
    done = client.get("/api/meetings", params={"status": "done"}).json()
    assert [r["id"] for r in done] == ["m_old"]
    assert client.get("/api/meetings", params={"status": "bogus"}).status_code == 422


# ---- POST /api/meetings/{id}/notes ----


def test_notes_unknown_meeting_404(client: TestClient) -> None:
    response = client.post("/api/meetings/nope/notes", json={"transcript": LONG_NOTE})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_notes_too_short_422(client: TestClient) -> None:
    response = client.post("/api/meetings/m4_finedge/notes", json={"transcript": "too short"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_notes_ingest_flow_done_with_learned_summary(
    client: TestClient, engine: Engine, llm: FakeLLM, memory: FakeMemoryService
) -> None:
    transcript = (TRANSCRIPTS / "m4_finedge_pilot_scoping.txt").read_text(encoding="utf-8")
    llm.queue_response(
        MeetingExtraction.model_validate_json((FIXTURES / "m4_extraction.json").read_text())
    )
    response = client.post("/api/meetings/m4_finedge/notes", json={"transcript": transcript})
    assert response.status_code == 202
    job_id = JobAccepted.model_validate(response.json()).job_id
    assert job_id.startswith("job_")

    # TestClient has run the background task by now.
    job = _job(client, job_id)
    assert job.status == "done" and job.kind == "ingest" and job.error is None
    assert job.learned is not None
    assert job.learned.new_commitments > 0
    assert job.learned.facts
    assert job.learned.closed_commitments == 0 and job.learned.alerts == []
    meeting = _meeting(engine, "m4_finedge")
    assert meeting.status == "done" and meeting.ingested_at is not None
    assert meeting.transcript == transcript
    assert len(memory.items) >= 1


def test_notes_saves_transcript_but_not_done_until_ingest_runs(
    client: TestClient, engine: Engine, llm: FakeLLM
) -> None:
    seen: dict[str, Meeting] = {}

    class Spy(FakeLLM):
        async def complete_json(self, prompt: str, schema: type[Any], **kwargs: Any) -> Any:
            seen["during"] = _meeting(engine, "m4_finedge")
            return _empty_extraction()

    main_module.app.dependency_overrides[get_llm_client_for_ingest] = lambda: Spy()
    response = client.post("/api/meetings/m4_finedge/notes", json={"transcript": LONG_NOTE})
    assert response.status_code == 202
    assert seen["during"].transcript == LONG_NOTE
    assert seen["during"].status == "upcoming" and seen["during"].ingested_at is None
    assert _meeting(engine, "m4_finedge").status == "done"


def test_notes_for_upcoming_live_meeting_m6(
    client: TestClient, engine: Engine, llm: FakeLLM
) -> None:
    llm.queue_response(_empty_extraction())
    response = client.post("/api/meetings/m6_finedge/notes", json={"transcript": LONG_NOTE})
    assert response.status_code == 202
    job = _job(client, response.json()["job_id"])
    assert job.status == "done" and job.learned == LearnedSummary(
        facts=[], new_commitments=0, closed_commitments=0, alerts=[]
    )
    assert _meeting(engine, "m6_finedge").status == "done"


def test_failing_llm_marks_job_failed_with_code(
    client: TestClient, engine: Engine, llm: FakeLLM
) -> None:
    llm.queue_error(LLMTimeoutError("timed out"))
    response = client.post("/api/meetings/m4_finedge/notes", json={"transcript": LONG_NOTE})
    assert response.status_code == 202
    job = _job(client, response.json()["job_id"])
    assert job.status == "failed" and job.error == "llm_timeout" and job.learned is None
    meeting = _meeting(engine, "m4_finedge")
    assert meeting.status == "upcoming" and meeting.ingested_at is None


def test_post_returns_before_ingest_runs(
    client: TestClient, engine: Engine, memory: FakeMemoryService
) -> None:
    """The 202 must be sent while a slow ingest is still pending (acceptance item 1)."""
    slow = SlowLLM()
    slow.queue_response(_empty_extraction())
    main_module.app.dependency_overrides[get_llm_client_for_ingest] = lambda: slow

    body = NotesRequest(transcript=LONG_NOTE).model_dump_json().encode()
    sent: dict[str, float] = {}

    async def drive() -> float:
        started = time.monotonic()
        delivered = False

        async def receive() -> dict[str, Any]:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            await asyncio.sleep(3600)
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                sent["status"] = message["status"]
                sent["at"] = time.monotonic() - started

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "path": "/api/meetings/m4_finedge/notes",
            "raw_path": b"/api/meetings/m4_finedge/notes",
            "query_string": b"",
            "root_path": "",
            "scheme": "http",
            "headers": [(b"content-type", b"application/json")],
            "server": ("test", 80),
            "client": ("test", 1),
        }
        await main_module.app(scope, receive, send)  # type: ignore[arg-type]
        return time.monotonic() - started

    total = asyncio.run(drive())
    assert sent["status"] == 202
    assert sent["at"] < 0.9
    assert total >= 1.0  # the background ingest did run to completion afterwards
    assert _meeting(engine, "m4_finedge").status == "done"


# ---- GET /api/jobs/{id} ----


def test_unknown_job_404(client: TestClient) -> None:
    response = client.get("/api/jobs/job_nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_pending_job_status(client: TestClient, engine: Engine) -> None:
    from app.db import ingest_repo

    with Session(engine) as db:
        job_id = ingest_repo.create_job_row(db).id
    job = _job(client, job_id)
    assert (job.status, job.learned, job.error) == ("pending", None, None)


# ---- app wiring ----


def test_openapi_paths_and_models(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    assert set(paths["/api/meetings"]) == {"get", "post"}
    assert "/api/accounts" in paths
    assert "/api/contacts" in paths
    assert "/api/meetings/{meeting_id}/prepared" in paths
    assert "202" in paths["/api/meetings/{meeting_id}/notes"]["post"]["responses"]
    assert "/api/jobs/{job_id}" in paths
    schemas = spec["components"]["schemas"]
    for model in (MeetingSummary, JobAccepted, JobStatus, LearnedSummary, NotesRequest):
        assert isinstance(model, type) and issubclass(model, BaseModel)
        assert set(schemas[model.__name__]["properties"]) == set(model.model_fields)
    ref = paths["/api/jobs/{job_id}"]["get"]["responses"]["200"]["content"]["application/json"]
    assert ref["schema"]["$ref"].endswith("/JobStatus")


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        llm_provider="openai",
        llm_model="gpt-test",
        openai_api_key="sk-test",
        hindsight_llm_provider="groq",
        hindsight_llm_model="hs",
        hindsight_llm_api_key="sk-test",
    )


def test_app_starts_without_touching_hindsight(
    monkeypatch: pytest.MonkeyPatch, engine: Engine
) -> None:
    constructed: list[object] = []

    class Boom:
        def __init__(self) -> None:
            constructed.append(self)
            raise AssertionError("memory service must not be built at startup")

    monkeypatch.setattr(deps, "HindsightMemoryService", Boom)
    monkeypatch.setattr(deps, "_memory", None)
    monkeypatch.setattr(main_module, "settings", _settings())
    monkeypatch.setattr(db_session, "engine", engine)
    plain = TestClient(main_module.app)  # no lifespan
    assert plain.get("/api/health").json() == {
        "status": "ok",
        "demo_today": "2026-09-28",
        "ae_name": "Priya Nair",
        "company_name": "Tracewise",
    }
    with TestClient(main_module.app) as started:
        assert started.get("/api/health").json() == {
            "status": "ok",
            "demo_today": "2026-09-28",
            "ae_name": "Priya Nair",
            "company_name": "Tracewise",
        }
        assert started.get("/api/meetings").json() == []  # tables created by the lifespan
    assert constructed == []


def test_lifespan_closes_memory_service_if_created(
    monkeypatch: pytest.MonkeyPatch, engine: Engine
) -> None:
    closed: list[bool] = []

    class Stub:
        async def aclose(self) -> None:
            closed.append(True)

    monkeypatch.setattr(deps, "_memory", None)
    monkeypatch.setattr(deps, "HindsightMemoryService", Stub)
    monkeypatch.setattr(main_module, "settings", _settings())
    monkeypatch.setattr(db_session, "engine", engine)
    with TestClient(main_module.app):
        assert isinstance(get_memory_service(), Stub)
        assert get_memory_service() is get_memory_service()
    assert closed == [True]
    assert deps._memory is None


def test_failed_job_result_message_is_not_exposed_only_the_code(
    client: TestClient, engine: Engine
) -> None:
    from app.db import ingest_repo

    learned = LearnedSummary(facts=[], new_commitments=1, closed_commitments=0, alerts=[])
    with Session(engine) as db:
        failed = ingest_repo.create_job_row(db).id
        ingest_repo.finish_job(
            db,
            failed,
            error="memory_unavailable",
            result={"error_code": "memory_unavailable", "error_message": "Retain timed out"},
        )
        done = ingest_repo.create_job_row(db).id
        ingest_repo.finish_job(db, done, result=learned.model_dump())
    job = _job(client, failed)
    assert job.status == "failed" and job.error == "memory_unavailable" and job.learned is None
    assert "Retain timed out" not in str(client.get(f"/api/jobs/{failed}").json())
    ok = _job(client, done)
    assert ok.status == "done" and ok.error is None and ok.learned is not None
    assert ok.learned.new_commitments == 1
