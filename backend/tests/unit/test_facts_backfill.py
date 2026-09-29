"""Tests for the one-time P1-only extracted-facts backfill."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.db import facts_repo
from app.db.models import Account, Contact, Meeting
from app.schemas.enums import FactKind
from app.schemas.extraction import ExtractedFact, MeetingExtraction
from app.services.facts_backfill import backfill_facts
from tests.fakes.fake_llm import FakeLLM


@pytest.fixture
def backfill_db(tmp_path: Path) -> Iterator[tuple[object, object]]:
    engine = create_engine(f"sqlite:///{tmp_path / 'backfill.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account(id="acc_x", name="X", industry="tech", stage="discovery"))
        session.add(Contact(id="c_x", account_id="acc_x", name="Xavier"))
        session.add(
            Meeting(
                id="m_x",
                account_id="acc_x",
                title="Call",
                scheduled_at=datetime(2026, 9, 1, tzinfo=UTC),
                status="done",
                transcript="Xavier: Budget is forty thousand dollars. We need EU hosting.",
            )
        )
        session.commit()

    def factory() -> Session:
        return Session(engine)

    yield engine, factory
    engine.dispose()


async def test_backfill_dry_run_makes_no_llm_calls_or_writes(
    backfill_db: tuple[object, object],
) -> None:
    _engine, factory_obj = backfill_db
    factory = factory_obj
    result = await backfill_facts(factory, None, dry_run=True)
    assert result.eligible == 1 and result.calls == 0 and result.processed == []
    with factory() as session:
        assert facts_repo.list_account_facts(session, "acc_x") == []


async def test_backfill_runs_p1_only_and_is_resumable(backfill_db: tuple[object, object]) -> None:
    _engine, factory_obj = backfill_db
    factory = factory_obj
    llm = FakeLLM()
    llm.queue_response(
        MeetingExtraction(
            people=[],
            commitments=[],
            acknowledgements=[],
            facts=[
                ExtractedFact(
                    kind=FactKind.deal_fact,
                    about_person=None,
                    text="Budget is $40K",
                    source_quote="Budget is forty thousand dollars.",
                ),
                ExtractedFact(
                    kind=FactKind.objection,
                    about_person="Xavier",
                    text="Needs EU hosting",
                    source_quote="We need EU hosting.",
                ),
            ],
            deal_budget_usd=40000,
        )
    )

    result = await backfill_facts(factory, llm, limit=1)
    assert result.eligible == 1 and result.calls == 1
    assert result.meetings_with_two_facts == 1
    assert result.facts_by_meeting["m_x"] == {"deal_fact": 1, "objection": 1}
    assert [call.schema for call in llm.calls] == [MeetingExtraction]
    with factory() as session:
        rows = facts_repo.list_account_facts(session, "acc_x")
        meeting = session.get(Meeting, "m_x")
        assert len(rows) == 2
        assert next(row for row in rows if row.kind == FactKind.objection).contact_id == "c_x"
        assert meeting is not None and meeting.status == "done"

    next_run = await backfill_facts(factory, FakeLLM())
    assert next_run.eligible == 0 and next_run.calls == 0
