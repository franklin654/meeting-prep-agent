"""Capture preview/save tests: P1/P2 happen only during preview."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

import app.main as main_module
from app.api.deps import (
    get_llm_client_for_ingest,
    get_memory_service,
    get_session,
    get_session_factory,
)
from app.db.models import Account, Commitment, Contact, ExtractedFact, Meeting
from app.schemas.ack import AckMatches, RenewedMatch
from app.schemas.enums import CommitmentStatus, FactKind, Owner
from app.schemas.extraction import ExtractedCommitment, MeetingExtraction
from app.schemas.extraction import ExtractedFact as ExtractedFactOutput
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fake_memory_service import FakeMemoryService

TRANSCRIPT = (
    "Alice: I will send the revised proposal by Friday. "
    "Alice: The pilot needs EU hosting. "
    "Alice: We are targeting a September launch."
)


@pytest.fixture
def capture_client(tmp_path: Path) -> Iterator[tuple[TestClient, Any, FakeLLM, FakeMemoryService]]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'capture.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account(id="acc_new", name="New Co", industry="tech", stage="discovery"))
        session.add(Contact(id="c_alice", account_id="acc_new", name="Alice"))
        session.add(
            Meeting(
                id="m_new",
                account_id="acc_new",
                title="Pilot",
                scheduled_at=datetime(2026, 9, 30, tzinfo=UTC),
                status="upcoming",
            )
        )
        session.commit()
    llm = FakeLLM()
    memory = FakeMemoryService()

    def session_dep() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    overrides = main_module.app.dependency_overrides
    overrides[get_session] = session_dep
    overrides[get_session_factory] = lambda: lambda: Session(engine)
    overrides[get_llm_client_for_ingest] = lambda: llm
    overrides[get_memory_service] = lambda: memory
    yield TestClient(main_module.app), engine, llm, memory
    overrides.clear()
    engine.dispose()


def extraction() -> MeetingExtraction:
    return MeetingExtraction(
        people=[],
        commitments=[
            ExtractedCommitment(
                owner=Owner.them,
                owner_person="Alice",
                text="Send the revised proposal",
                due_date=None,
                source_quote="I will send the revised proposal by Friday.",
            )
        ],
        acknowledgements=[],
        facts=[
            ExtractedFactOutput(
                kind=FactKind.deal_fact,
                about_person=None,
                text="Needs EU hosting",
                source_quote="The pilot needs EU hosting.",
            ),
            ExtractedFactOutput(
                kind=FactKind.deal_fact,
                about_person=None,
                text="Targeting September launch",
                source_quote="We are targeting a September launch.",
            ),
        ],
        deal_budget_usd=None,
    )


def test_preview_is_side_effect_free_and_save_applies_only_selected_items(
    capture_client: tuple[TestClient, Any, FakeLLM, FakeMemoryService],
) -> None:
    client, engine, llm, memory = capture_client
    llm.queue_response(extraction())
    preview = client.post("/api/meetings/m_new/capture/preview", json={"transcript": TRANSCRIPT})
    assert preview.status_code == 202
    job = client.get(f"/api/jobs/{preview.json()['job_id']}").json()
    draft = job["draft"]
    assert draft["counts"] == {"commitments": 1, "closes": 0, "facts": 2}
    assert len(llm.calls) == 1
    assert memory.items == []
    with Session(engine) as session:
        assert not session.exec(select(Commitment)).all()
        assert not session.exec(select(ExtractedFact)).all()
        assert session.get(Meeting, "m_new").transcript is None

    unchecked = [
        item["id"] for item in draft["items"] if item["text"] == "Targeting September launch"
    ]
    saved = client.post(
        f"/api/capture/{draft['draft_id']}/save", json={"unchecked_item_ids": unchecked}
    )
    assert saved.status_code == 202
    save_job_id = saved.json()["job_id"]
    assert client.get(f"/api/jobs/{save_job_id}").json()["status"] == "done"
    assert len(llm.calls) == 1  # save uses the reviewed P1 result, never a second P1/P2
    assert len(memory.items) == 1
    with Session(engine) as session:
        assert len(session.exec(select(Commitment)).all()) == 1
        facts = session.exec(select(ExtractedFact)).all()
        assert [row.text for row in facts] == ["Needs EU hosting"]
        assert session.get(Meeting, "m_new").status == "done"

    repeated = client.post(
        f"/api/capture/{draft['draft_id']}/save", json={"unchecked_item_ids": []}
    )
    assert repeated.json()["job_id"] == save_job_id


def test_discard_does_not_write_ledger_or_memory(
    capture_client: tuple[TestClient, Any, FakeLLM, FakeMemoryService],
) -> None:
    client, engine, llm, memory = capture_client
    llm.queue_response(extraction())
    preview = client.post("/api/meetings/m_new/capture/preview", json={"transcript": TRANSCRIPT})
    draft_id = client.get(f"/api/jobs/{preview.json()['job_id']}").json()["draft"]["draft_id"]
    assert client.delete(f"/api/capture/{draft_id}").status_code == 204
    with Session(engine) as session:
        assert not session.exec(select(Commitment)).all()
        assert not session.exec(select(ExtractedFact)).all()
    assert memory.items == []


def test_preview_rejects_transcript_over_200kb(
    capture_client: tuple[TestClient, Any, FakeLLM, FakeMemoryService],
) -> None:
    client, _engine, _llm, _memory = capture_client
    response = client.post(
        "/api/meetings/m_new/capture/preview", json={"transcript": "x" * 200_001}
    )
    assert response.status_code == 422


def test_duplicate_and_renewal_badges(
    capture_client: tuple[TestClient, Any, FakeLLM, FakeMemoryService],
) -> None:
    client, engine, llm, _memory = capture_client
    with Session(engine) as session:
        session.add(
            Commitment(
                id="cm_existing",
                account_id="acc_new",
                meeting_id="m_new",
                owner=Owner.them,
                contact_id="c_alice",
                text="Send the revised proposal",
                due_date=None,
                status=CommitmentStatus.open,
                source_quote="I will send the revised proposal.",
            )
        )
        session.commit()
    llm.queue_response(extraction())
    llm.queue_response(AckMatches(closed=[], renewed=[]))
    response = client.post("/api/meetings/m_new/capture/preview", json={"transcript": TRANSCRIPT})
    items = client.get(f"/api/jobs/{response.json()['job_id']}").json()["draft"]["items"]
    commitment = next(item for item in items if item["kind"] == "commitment")
    assert commitment["badge"] == "duplicate"
    assert commitment["checked"] is False


def test_renewal_is_badged_as_due_date_update(
    capture_client: tuple[TestClient, Any, FakeLLM, FakeMemoryService],
) -> None:
    client, engine, llm, _memory = capture_client
    with Session(engine) as session:
        session.add(
            Commitment(
                id="cm_existing",
                account_id="acc_new",
                meeting_id="m_new",
                owner=Owner.them,
                contact_id="c_alice",
                text="Send the revised proposal",
                due_date=None,
                status=CommitmentStatus.open,
                source_quote="I will send the revised proposal.",
            )
        )
        session.commit()
    renewed_extraction = extraction()
    renewed_extraction.commitments[0].due_date = datetime(2026, 10, 2, tzinfo=UTC).date()
    llm.queue_response(renewed_extraction)
    llm.queue_response(
        AckMatches(
            closed=[], renewed=[RenewedMatch(commitment_id="cm_existing", commitment_index=0)]
        )
    )
    response = client.post("/api/meetings/m_new/capture/preview", json={"transcript": TRANSCRIPT})
    items = client.get(f"/api/jobs/{response.json()['job_id']}").json()["draft"]["items"]
    commitment = next(item for item in items if item["kind"] == "commitment")
    assert commitment["badge"] == "updates_due_date"
    assert commitment["target_commitment_id"] == "cm_existing"
