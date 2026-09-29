"""T12: ingest service, prompts P1/P2 and ingest_repo, all against FakeLLM/FakeMemoryService.

M4/M5 use the real seed transcripts so the verbatim-quote check runs against real text
(curly apostrophes included); the LLM answers are recorded fixtures (tests/unit/fixtures).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.errors import (
    LLMInvalidOutputError,
    LLMTimeoutError,
    MemoryUnavailableError,
    NotFoundError,
    RateLimitedError,
)
from app.core.time import utcnow
from app.db import ingest_repo
from app.db import repository as repo
from app.db.models import Account, Commitment, Contact, Job, Meeting
from app.llm.prompt_loader import prompt_placeholders, render_prompt
from app.schemas.ack import AckMatches, ClosedMatch
from app.schemas.enums import CommitmentStatus, Owner
from app.schemas.extraction import (
    Acknowledgement,
    ExtractedCommitment,
    ExtractedFact,
    MeetingExtraction,
    PersonMention,
)
from app.services import ingest
from app.services.ingest import (
    INGEST_LLM_TIMEOUT_SECONDS,
    default_ingest_llm,
    is_verbatim,
    normalize_text,
    run_ingest,
    run_ingest_job,
)
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fake_memory_service import FakeMemoryService

ROOT = Path(__file__).resolve().parents[3]
TRANSCRIPTS = ROOT / "data" / "seed" / "transcripts"
FIXTURES = Path(__file__).parent / "fixtures"

SessionFactory = Callable[[], AbstractContextManager[Session]]


def _extraction(name: str) -> MeetingExtraction:
    return MeetingExtraction.model_validate_json((FIXTURES / name).read_text())


def _transcript(name: str) -> str:
    return (TRANSCRIPTS / name).read_text(encoding="utf-8")


# ---- fixtures ----


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    eng = create_engine(
        f"sqlite:///{tmp_path / 'ingest.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def factory(engine: Engine) -> SessionFactory:
    return lambda: Session(engine)


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with Session(engine) as s:
        yield s


@pytest.fixture
def seeded(db: Session) -> Session:
    """FinEdge account, our two people, four account contacts, meetings M4, M5, M6."""
    repo.create_account(
        db,
        Account(id="acc_finedge", name="FinEdge Payments", industry="fintech", stage="evaluation"),
    )
    for cid, name, role, acct, aliases in [
        ("c_priya", "Priya Nair", "Account Executive", None, []),
        ("c_arjun", "Arjun Menon", "Sales Engineer", None, []),
        ("c_rahul", "Rahul Mehta", "VP Engineering", "acc_finedge", []),
        ("c_anita", "Anita Desai", "CFO", "acc_finedge", []),
        ("c_karan", "Karan Shah", "Data Platform Lead", "acc_finedge", ["KS"]),
    ]:
        repo.create_contact(
            db, Contact(id=cid, account_id=acct, name=name, role=role, aliases=aliases)
        )
    for mid, day, title, who, tfile in [
        (
            "m4_finedge",
            datetime(2026, 8, 27, 10, tzinfo=UTC),
            "Pilot scoping",
            ["c_priya", "c_arjun", "c_rahul", "c_karan"],
            "m4_finedge_pilot_scoping.txt",
        ),
        (
            "m5_finedge",
            datetime(2026, 9, 15, 10, tzinfo=UTC),
            "Check-in",
            ["c_priya", "c_karan"],
            "m5_finedge_check_in.txt",
        ),
        (
            "m6_finedge",
            datetime(2026, 9, 29, 10, tzinfo=UTC),
            "Pilot decision",
            ["c_priya", "c_rahul", "c_anita", "c_karan"],
            None,
        ),
    ]:
        repo.create_meeting(
            db,
            Meeting(
                id=mid,
                account_id="acc_finedge",
                title=title,
                scheduled_at=day,
                status="upcoming",
                transcript=_transcript(tfile) if tfile else None,
            ),
        )
        for cid in who:
            repo.add_attendee(db, mid, cid)
    return db


def _job(db: Session) -> str:
    return ingest_repo.create_job_row(db).id


async def _ingest_m4(
    seeded: Session, factory: SessionFactory, llm: FakeLLM, memory: FakeMemoryService
) -> str:
    llm.queue_response(_extraction("m4_extraction.json"))
    job_id = _job(seeded)
    await run_ingest(job_id, "m4_finedge", llm=llm, memory=memory, session_factory=factory)
    return job_id


def _commitments(db: Session) -> list[Commitment]:
    db.expire_all()
    return sorted(db.exec(select(Commitment)).all(), key=lambda c: c.text)


def _by_text(db: Session, needle: str) -> Commitment:
    return next(c for c in _commitments(db) if needle in c.text)


# ---- prompts and schema ----


def test_p1_p2_render_and_placeholders() -> None:
    assert prompt_placeholders("extract_meeting") == [
        "our_company",
        "our_people",
        "meeting_title",
        "meeting_date",
        "account_name",
        "known_contacts",
        "transcript",
    ]
    text = render_prompt(
        "extract_meeting",
        our_company="Tracewise",
        our_people="Priya",
        meeting_title="T",
        meeting_date="2026-08-27",
        account_name="FinEdge",
        known_contacts="Karan",
        transcript="X",
    )
    assert '"source_quote"' in text and "{" in text  # escaped example braces survive
    p2 = render_prompt(
        "match_acknowledgements",
        open_commitments="cm_1: a",
        meeting_date="2026-09-15",
        acknowledgements="0: x",
    )
    assert '{"closed": [' in p2 and "never a match" in p2


def test_ack_matches_forbids_extra_fields() -> None:
    parsed = AckMatches.model_validate(
        {"closed": [{"commitment_id": "cm_1", "acknowledgement_index": 0}]}
    )
    assert parsed.closed == [ClosedMatch(commitment_id="cm_1", acknowledgement_index=0)]
    with pytest.raises(PydanticValidationError):
        AckMatches.model_validate({"closed": [], "extra": 1})


def test_normalize_text_forgives_case_quotes_and_whitespace_only() -> None:
    norm = normalize_text("Karan:   It’s  STILL 55\nin production.")
    assert is_verbatim("it's still 55 in production", norm)
    assert not is_verbatim("it's still 56 in production", norm)
    assert not is_verbatim("", norm)


def test_default_ingest_llm_uses_120s_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    sentinel = FakeLLM()

    def fake_get(*args: Any, **kwargs: Any) -> FakeLLM:
        seen.update(kwargs)
        return sentinel

    monkeypatch.setattr(ingest, "get_llm_client", fake_get)
    assert default_ingest_llm() is sentinel
    assert INGEST_LLM_TIMEOUT_SECONDS == 120
    assert seen == {"timeout_seconds": 120}


# ---- M4 ----


async def test_m4_commitments_quotes_and_no_commitment_in_facts(
    seeded: Session, factory: SessionFactory
) -> None:
    llm, memory = FakeLLM(), FakeMemoryService()
    job_id = await _ingest_m4(seeded, factory, llm, memory)

    rows = _commitments(seeded)
    assert len(rows) == 2
    deck, dag = _by_text(seeded, "pricing deck"), _by_text(seeded, "DAG configs")
    assert (deck.owner, deck.due_date, deck.contact_id) == (Owner.us, date(2026, 9, 3), "c_priya")
    assert (dag.owner, dag.due_date, dag.contact_id) == (Owner.them, date(2026, 9, 5), "c_karan")
    transcript = normalize_text(_transcript("m4_finedge_pilot_scoping.txt"))
    for row in rows:
        assert row.status == CommitmentStatus.open
        assert normalize_text(row.source_quote) in transcript
    job = repo.get_job(seeded, job_id)
    assert job is not None and job.status == "done" and job.error is None
    assert job.result is not None
    assert job.result["new_commitments"] == 2 and job.result["closed_commitments"] == 0
    assert job.result["facts"] == ["55 pipelines in production"]
    assert not any("deck" in f or "DAG" in f for f in job.result["facts"])
    # P1 only: no acknowledgements, so P2 never ran; temperature 0.
    assert [c.schema for c in llm.calls] == [MeetingExtraction]
    assert llm.calls[0].temperature == 0.0
    assert "Tracewise" in llm.calls[0].prompt and "Karan Shah" in llm.calls[0].prompt


async def test_retained_once_with_right_kwargs_then_meeting_done(
    seeded: Session, factory: SessionFactory
) -> None:
    llm, memory = FakeLLM(), FakeMemoryService()
    await _ingest_m4(seeded, factory, llm, memory)

    assert len(memory.items) == 1
    item = memory.items[0]
    assert item.document_id == "meeting-m4_finedge"
    assert item.meeting_id == "m4_finedge" and item.meeting_date == date(2026, 8, 27)
    assert item.title == "Pilot scoping"
    assert item.text == _transcript("m4_finedge_pilot_scoping.txt")
    for tag in ("account:acc_finedge", "contact:c_priya", "contact:c_karan", "contact:c_rahul"):
        assert tag in item.tags
    seeded.expire_all()
    meeting = repo.get_meeting(seeded, "m4_finedge")
    assert meeting is not None and meeting.status == "done" and meeting.ingested_at is not None


# ---- M5 ----


async def test_m5_closes_dag_configs_and_keeps_deck_open_and_overdue(
    seeded: Session, factory: SessionFactory
) -> None:
    llm, memory = FakeLLM(), FakeMemoryService()
    await _ingest_m4(seeded, factory, llm, memory)
    dag_id = _by_text(seeded, "DAG configs").id
    deck_id = _by_text(seeded, "pricing deck").id

    llm.queue_response(_extraction("m5_extraction.json"))
    # The model correctly matches only index 0 (the DAG thanks), never the distractor (1).
    llm.queue_response(
        AckMatches(closed=[ClosedMatch(commitment_id=dag_id, acknowledgement_index=0)])
    )
    job_id = _job(seeded)
    summary = await run_ingest(
        job_id, "m5_finedge", llm=llm, memory=memory, session_factory=factory
    )

    dag, deck = _by_text(seeded, "DAG configs"), _by_text(seeded, "pricing deck")
    assert (dag.status, dag.closed_by_meeting_id) == (CommitmentStatus.done, "m5_finedge")
    assert (deck.status, deck.closed_by_meeting_id) == (CommitmentStatus.open, None)
    assert deck.id == deck_id
    overdue = repo.list_overdue_commitments(seeded, account_id="acc_finedge")
    assert [c.id for c in overdue] == [deck_id]  # demo today is 2026-09-28, due 2026-09-03
    assert summary.closed_commitments == 1 and summary.new_commitments == 0
    # P2 prompt lists both open earlier commitments and both acknowledgements.
    p2 = llm.calls[-1]
    assert p2.schema is AckMatches and p2.temperature == 0.0
    assert dag_id in p2.prompt and deck_id in p2.prompt and "still waiting" in p2.prompt
    # Budget stated ($40K) -> account deal value.
    acct = repo.get_account(seeded, "acc_finedge")
    assert acct is not None and acct.deal_value_usd == 40000


async def test_p2_unknown_ids_and_out_of_range_indexes_are_dropped(
    seeded: Session, factory: SessionFactory
) -> None:
    llm, memory = FakeLLM(), FakeMemoryService()
    await _ingest_m4(seeded, factory, llm, memory)
    deck_id = _by_text(seeded, "pricing deck").id

    llm.queue_response(_extraction("m5_extraction.json"))
    llm.queue_response(
        AckMatches(
            closed=[
                ClosedMatch(commitment_id="cm_doesnotexist", acknowledgement_index=0),
                ClosedMatch(commitment_id=deck_id, acknowledgement_index=7),
            ]
        )
    )
    summary = await run_ingest(
        _job(seeded), "m5_finedge", llm=llm, memory=memory, session_factory=factory
    )
    assert summary.closed_commitments == 0
    assert _by_text(seeded, "pricing deck").status == CommitmentStatus.open


async def test_empty_acknowledgements_skip_p2(seeded: Session, factory: SessionFactory) -> None:
    llm, memory = FakeLLM(), FakeMemoryService()
    await _ingest_m4(seeded, factory, llm, memory)
    m5 = _extraction("m5_extraction.json").model_copy(update={"acknowledgements": []})
    llm.queue_response(m5)
    before = len(llm.calls)
    await run_ingest(_job(seeded), "m5_finedge", llm=llm, memory=memory, session_factory=factory)
    assert len(llm.calls) - before == 1  # P1 only


async def test_p2_skipped_when_no_earlier_open_commitments(
    seeded: Session, factory: SessionFactory
) -> None:
    llm, memory = FakeLLM(), FakeMemoryService()
    llm.queue_response(_extraction("m5_extraction.json"))  # M5 with acks but ledger empty
    await run_ingest(_job(seeded), "m5_finedge", llm=llm, memory=memory, session_factory=factory)
    assert len(llm.calls) == 1


async def test_p2_never_sees_commitments_this_transcript_creates(
    seeded: Session, factory: SessionFactory
) -> None:
    llm, memory = FakeLLM(), FakeMemoryService()
    both = _extraction("m4_extraction.json").model_copy(
        update={
            "acknowledgements": [
                Acknowledgement(
                    description="sample configs",
                    source_quote="I'll send sample DAG configs by Sep 5.",
                )
            ]
        }
    )
    llm.queue_response(both)
    await run_ingest(_job(seeded), "m4_finedge", llm=llm, memory=memory, session_factory=factory)
    assert len(llm.calls) == 1  # nothing earlier is open, so no P2
    assert all(c.status == CommitmentStatus.open for c in _commitments(seeded))


async def test_later_meeting_commitments_are_not_matchable_by_earlier_rerun(
    seeded: Session, factory: SessionFactory
) -> None:
    llm, memory = FakeLLM(), FakeMemoryService()
    await _ingest_m4(seeded, factory, llm, memory)
    # M6 (later) re-promises the deck; ingesting it later must not crash.
    repo.update_meeting_transcript(
        seeded,
        "m6_finedge",
        transcript="Priya Nair: I will resend the deck by Friday. " * 3,
        ingested_at=datetime(2026, 9, 1, 0, tzinfo=UTC),
    )
    m6 = MeetingExtraction(
        people=[],
        acknowledgements=[],
        facts=[],
        deal_budget_usd=75000,
        commitments=[
            ExtractedCommitment(
                owner=Owner.us,
                owner_person="Priya",
                text="Resend the deck",
                due_date=None,
                source_quote="I will resend the deck by Friday.",
            )
        ],
    )
    llm.queue_response(m6)
    await run_ingest(_job(seeded), "m6_finedge", llm=llm, memory=memory, session_factory=factory)
    assert len(_commitments(seeded)) == 3
    # Rerunning M5 must not see M6's commitment as matchable.
    llm.queue_response(_extraction("m5_extraction.json"))
    llm.queue_response(AckMatches(closed=[]))
    await run_ingest(_job(seeded), "m5_finedge", llm=llm, memory=memory, session_factory=factory)
    p2_prompt = llm.calls[-1].prompt
    assert "Resend the deck" not in p2_prompt and "pricing deck" in p2_prompt


# ---- filtering and resolution ----


async def test_fabricated_quotes_are_dropped(seeded: Session, factory: SessionFactory) -> None:
    llm, memory = FakeLLM(), FakeMemoryService()
    ext = _extraction("m4_extraction.json")
    ext = ext.model_copy(
        update={
            "commitments": [
                *ext.commitments,
                ExtractedCommitment(
                    owner=Owner.us,
                    owner_person="Priya",
                    text="Send a unicorn",
                    due_date=None,
                    source_quote="I promise to send a unicorn by Monday.",
                ),
            ],
            "facts": [
                ExtractedFact(
                    kind="deal_fact",
                    about_person=None,
                    text="Made up",  # type: ignore[arg-type]
                    source_quote="the budget is a million dollars",
                )
            ],
        }
    )
    llm.queue_response(ext)
    job_id = _job(seeded)
    summary = await run_ingest(
        job_id, "m4_finedge", llm=llm, memory=memory, session_factory=factory
    )
    assert [c.text for c in _commitments(seeded)] == [
        "Send revised pricing deck with pilot option",
        "Send sample DAG configs",
    ]
    assert summary.facts == []


async def test_alias_ks_resolves_to_c_karan_without_creating_contacts(
    seeded: Session, factory: SessionFactory
) -> None:
    llm, memory = FakeLLM(), FakeMemoryService()
    ext = _extraction("m4_extraction.json")
    ext = ext.model_copy(
        update={
            "people": [
                *ext.people,
                PersonMention(name_as_said="KS", role_if_stated=None, organisation=None),
            ]
        }
    )
    llm.queue_response(ext)
    await run_ingest(_job(seeded), "m4_finedge", llm=llm, memory=memory, session_factory=factory)
    assert _by_text(seeded, "DAG configs").contact_id == "c_karan"
    assert len(seeded.exec(select(Contact)).all()) == 5


async def test_unknown_speaker_creates_needs_review_contact(
    seeded: Session, factory: SessionFactory
) -> None:
    llm, memory = FakeLLM(), FakeMemoryService()
    ext = _extraction("m4_extraction.json")
    ext = ext.model_copy(
        update={
            "people": [
                *ext.people,
                PersonMention(
                    name_as_said="Dev Kapoor", role_if_stated="SRE", organisation="FinEdge"
                ),
                PersonMention(name_as_said="their CFO", role_if_stated=None, organisation=None),
            ]
        }
    )
    llm.queue_response(ext)
    await run_ingest(_job(seeded), "m4_finedge", llm=llm, memory=memory, session_factory=factory)
    seeded.expire_all()
    new = [c for c in seeded.exec(select(Contact)).all() if c.name == "Dev Kapoor"]
    assert len(new) == 1
    assert new[0].needs_review is True and new[0].account_id == "acc_finedge"
    assert new[0].id.startswith("c_") and len(new[0].id) == 10
    assert new[0].role == "SRE"
    assert not [c for c in seeded.exec(select(Contact)).all() if "CFO" in c.name]  # generic ref


# ---- budget ----


async def test_latest_budget_wins_and_is_integer(seeded: Session, factory: SessionFactory) -> None:
    llm, memory = FakeLLM(), FakeMemoryService()
    await _ingest_m4(seeded, factory, llm, memory)  # budget None: unchanged
    acct = repo.get_account(seeded, "acc_finedge")
    assert acct is not None and acct.deal_value_usd is None

    for m_name, value in (("m5_extraction.json", 40000),):
        llm.queue_response(_extraction(m_name))
        llm.queue_response(AckMatches(closed=[]))
        await run_ingest(
            _job(seeded), "m5_finedge", llm=llm, memory=memory, session_factory=factory
        )
        seeded.expire_all()
        acct = repo.get_account(seeded, "acc_finedge")
        assert acct is not None and acct.deal_value_usd == value

    llm.queue_response(
        MeetingExtraction(
            people=[], commitments=[], acknowledgements=[], facts=[], deal_budget_usd=75000
        )
    )
    repo.update_meeting_transcript(
        seeded,
        "m6_finedge",
        transcript="Anita Desai: we can go up to seventy five thousand. " * 2,
        ingested_at=datetime(2026, 9, 1, 0, tzinfo=UTC),
    )
    summary = await run_ingest(
        _job(seeded), "m6_finedge", llm=llm, memory=memory, session_factory=factory
    )
    seeded.expire_all()
    acct = repo.get_account(seeded, "acc_finedge")
    assert acct is not None and acct.deal_value_usd == 75000
    assert "Budget now $75,000 (was $40,000)" in summary.facts


# ---- idempotency ----


async def test_rerun_is_idempotent_and_reopens_then_recloses(
    seeded: Session, factory: SessionFactory
) -> None:
    llm, memory = FakeLLM(), FakeMemoryService()
    await _ingest_m4(seeded, factory, llm, memory)
    dag_id = _by_text(seeded, "DAG configs").id

    def m5_run_queue() -> None:
        llm.queue_response(_extraction("m5_extraction.json"))
        llm.queue_response(
            AckMatches(closed=[ClosedMatch(commitment_id=dag_id, acknowledgement_index=0)])
        )

    m5_run_queue()
    await run_ingest(_job(seeded), "m5_finedge", llm=llm, memory=memory, session_factory=factory)
    first = [(c.id, c.status, c.closed_by_meeting_id) for c in _commitments(seeded)]
    m5_run_queue()
    await run_ingest(_job(seeded), "m5_finedge", llm=llm, memory=memory, session_factory=factory)
    assert [(c.id, c.status, c.closed_by_meeting_id) for c in _commitments(seeded)] == first

    # Re-ingesting M4 deletes and recreates its commitments, no duplicates.
    llm.queue_response(_extraction("m4_extraction.json"))
    await run_ingest(_job(seeded), "m4_finedge", llm=llm, memory=memory, session_factory=factory)
    rows = _commitments(seeded)
    assert len(rows) == 2 and all(c.status == CommitmentStatus.open for c in rows)
    assert len(memory.items) == 2  # one document per meeting (stable ids replace)


# ---- failures ----


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (LLMTimeoutError("slow"), "llm_timeout"),
        (LLMInvalidOutputError("bad"), "llm_invalid_output"),
        (RateLimitedError("429"), "rate_limited"),
        (RuntimeError("boom"), "internal_error"),
    ],
)
async def test_llm_failures_mark_job_failed_and_meeting_not_ingested(
    seeded: Session, factory: SessionFactory, error: Exception, code: str
) -> None:
    llm, memory = FakeLLM(), FakeMemoryService()
    llm.queue_error(error)
    job_id = _job(seeded)
    with pytest.raises(type(error)):
        await run_ingest(job_id, "m4_finedge", llm=llm, memory=memory, session_factory=factory)
    seeded.expire_all()
    job = repo.get_job(seeded, job_id)
    assert job is not None and (job.status, job.error) == ("failed", code)
    assert job.finished_at is not None
    meeting = repo.get_meeting(seeded, "m4_finedge")
    assert meeting is not None and meeting.ingested_at is None
    assert memory.items == [] and len(llm.calls) == 1  # no silent retry at this layer


async def test_p2_timeout_fails_job(seeded: Session, factory: SessionFactory) -> None:
    llm, memory = FakeLLM(), FakeMemoryService()
    await _ingest_m4(seeded, factory, llm, memory)
    llm.queue_response(_extraction("m5_extraction.json"))
    llm.queue_error(LLMTimeoutError("slow"))
    job_id = _job(seeded)
    with pytest.raises(LLMTimeoutError):
        await run_ingest(job_id, "m5_finedge", llm=llm, memory=memory, session_factory=factory)
    seeded.expire_all()
    job = repo.get_job(seeded, job_id)
    assert job is not None and job.error == "llm_timeout"
    m5 = repo.get_meeting(seeded, "m5_finedge")
    assert m5 is not None and m5.ingested_at is None


async def test_retain_failure_leaves_meeting_not_done_and_rerun_recovers(
    seeded: Session, factory: SessionFactory
) -> None:
    class FailingMemory(FakeMemoryService):
        async def retain_meeting(self, **kwargs: Any) -> None:
            raise MemoryUnavailableError("down")

    llm = FakeLLM()
    llm.queue_response(_extraction("m4_extraction.json"))
    job_id = _job(seeded)
    with pytest.raises(MemoryUnavailableError):
        await run_ingest(
            job_id, "m4_finedge", llm=llm, memory=FailingMemory(), session_factory=factory
        )
    seeded.expire_all()
    job = repo.get_job(seeded, job_id)
    assert job is not None and job.error == "memory_unavailable"
    meeting = repo.get_meeting(seeded, "m4_finedge")
    assert meeting is not None and meeting.status == "upcoming" and meeting.ingested_at is None

    # Rerun after Hindsight recovers: no duplicate commitments, meeting now done.
    good = FakeMemoryService()
    llm.queue_response(_extraction("m4_extraction.json"))
    await run_ingest(_job(seeded), "m4_finedge", llm=llm, memory=good, session_factory=factory)
    assert len(_commitments(seeded)) == 2
    seeded.expire_all()
    meeting = repo.get_meeting(seeded, "m4_finedge")
    assert meeting is not None and meeting.status == "done"


async def test_missing_meeting_is_not_found_and_job_failed(
    seeded: Session, factory: SessionFactory
) -> None:
    job_id = _job(seeded)
    with pytest.raises(NotFoundError):
        await run_ingest(
            job_id, "nope", llm=FakeLLM(), memory=FakeMemoryService(), session_factory=factory
        )
    seeded.expire_all()
    job = repo.get_job(seeded, job_id)
    assert job is not None and job.status == "failed" and job.error == "not_found"


async def test_run_ingest_job_swallows_but_records(
    seeded: Session, factory: SessionFactory
) -> None:
    llm = FakeLLM()
    llm.queue_error(LLMTimeoutError("slow"))
    job_id = _job(seeded)
    await run_ingest_job(
        job_id, "m4_finedge", llm=llm, memory=FakeMemoryService(), session_factory=factory
    )
    seeded.expire_all()
    job = repo.get_job(seeded, job_id)
    assert job is not None and (job.status, job.error) == ("failed", "llm_timeout")


# ---- repo helpers ----


def test_repo_open_commitments_before_and_contacts_for_matching(seeded: Session) -> None:
    ingest_repo.create_commitment_rows(
        seeded,
        account_id="acc_finedge",
        meeting_id="m4_finedge",
        rows=[(Owner.us, "c_priya", "Deck", date(2026, 9, 3), "q")],
    )
    ingest_repo.create_commitment_rows(
        seeded,
        account_id="acc_finedge",
        meeting_id="m6_finedge",
        rows=[(Owner.us, None, "Later", None, "q")],
    )
    before_m5 = ingest_repo.list_open_commitments(
        seeded, "acc_finedge", before=datetime(2026, 9, 15, 10, tzinfo=UTC)
    )
    assert [c.text for c in before_m5] == ["Deck"]
    assert len(ingest_repo.list_open_commitments(seeded, "acc_finedge")) == 2
    names = {c.name for c in ingest_repo.list_contacts_for_matching(seeded, "acc_finedge")}
    assert {"Priya Nair", "Arjun Menon", "Karan Shah"} <= names
    meeting, attendees = ingest_repo.get_meeting_with_attendees(seeded, "m5_finedge")
    assert meeting.id == "m5_finedge" and {a.id for a in attendees} == {"c_priya", "c_karan"}


def test_repo_job_helpers_use_demo_clock_and_prefixed_ids(db: Session) -> None:
    job = ingest_repo.create_job_row(db)
    assert job.id.startswith("job_") and len(job.id) == 12 and job.status == "pending"
    assert abs(job.created_at - utcnow()) < timedelta(seconds=30)
    done = ingest_repo.finish_job(db, job.id, result={"facts": []})
    assert done.status == "done" and done.finished_at is not None
    assert abs(done.finished_at - utcnow()) < timedelta(seconds=30)
    other = ingest_repo.create_job_row(db)
    failed = ingest_repo.finish_job(db, other.id, error="llm_timeout")
    assert failed.status == "failed" and failed.error == "llm_timeout"
    assert len(db.exec(select(Job)).all()) == 2


async def test_ingested_at_is_wall_clock_later_than_earlier_stamp(
    seeded: Session, factory: SessionFactory
) -> None:
    before = utcnow()
    llm = FakeLLM()
    await _ingest_m4(seeded, factory, llm, FakeMemoryService())
    seeded.expire_all()
    meeting = repo.get_meeting(seeded, "m4_finedge")
    assert meeting is not None and meeting.ingested_at is not None
    assert meeting.ingested_at > before


# ---- T12b: tightened P1 + code-side consolidation ----


def _cm(
    text: str, quote: str, due: date | None = None, who: str = "Priya", owner: Owner = Owner.us
) -> ExtractedCommitment:
    return ExtractedCommitment(
        owner=owner, owner_person=who, text=text, due_date=due, source_quote=quote
    )


def _noisy_m4() -> list[ExtractedCommitment]:
    """14 noisy P1 commitments; every quote is a real substring of the M4 transcript."""
    process = [
        ("Keep the owner list short", "Keep the owner list short, please."),
        ("Stress that committees are unnecessary", "We don't need a committee for every DAG."),
        ("Confirm attendees can hear us", "Can you both hear us okay?"),
        ("Check that Arjun is on the call", "Arjun, you're on too?"),
        ("Greet the group warmly", "Morning, Rahul. Morning, Karan."),
        ("Note the production pipeline count", "It's still 55 in production."),
        ("Help map what would be sent", "I can help map what we'd send"),
        ("Spell out deployment data flows", "Sneha wants the deployment and data flow spelled out"),
    ]
    return [
        _cm(
            "Send the revised pricing deck with pilot option",
            "share the revised pricing deck on the date I mentioned",
        ),
        _cm(
            "Send revised pricing deck with pilot option",
            "I'll also send a revised pricing deck with the pilot option by Sep 3.",
            date(2026, 9, 3),
        ),
        _cm(
            "Send sample DAG configs",
            "I'll send sample DAG configs by Sep 5.",
            date(2026, 9, 5),
            who="Karan",
            owner=Owner.them,
        ),
        _cm("Put together the pilot outline", "I'll put those criteria into the pilot outline."),
        _cm(
            "Put together the pilot outline with success criteria and commercial assumptions",
            "put together the pilot outline, include the success criteria and commercial "
            "assumptions",
        ),
        *[_cm(t, q) for t, q in process],
        _cm(
            "Send sample DAG configs",
            "I'll send sample DAG configs by Sep 5.",
            who="Karan",
            owner=Owner.them,
        ),
    ]


def test_consolidate_merges_duplicates_and_caps_dated_first() -> None:
    noisy = _noisy_m4()
    assert len(noisy) == 14
    norm = normalize_text(_transcript("m4_finedge_pilot_scoping.txt"))
    kept, merged, capped = ingest.consolidate_commitments(noisy, norm)

    assert ingest.MAX_COMMITMENTS_PER_MEETING == 5 and len(kept) == 5
    assert merged == 3  # deck restatement, pilot outline restatement, DAG repeat
    assert capped == 5  # 14 - 1 logistics ('Confirm attendees...') - 3 merged = 10, 5 kept
    assert [c.due_date for c in kept[:2]] == [date(2026, 9, 3), date(2026, 9, 5)]
    deck = kept[0]
    assert deck.due_date == date(2026, 9, 3) and "pricing deck" in deck.text
    assert deck.source_quote.startswith("I'll also send a revised pricing deck")  # earliest
    assert sum("DAG configs" in c.text for c in kept) == 1
    assert all(c.due_date is None for c in kept[2:])


def test_consolidate_keeps_most_specific_text_on_containment() -> None:
    kept, merged, _ = ingest.consolidate_commitments(
        [
            _cm("Put together the pilot outline", "q1"),
            _cm("Put together the pilot outline with success criteria", "q2"),
        ]
    )
    assert merged == 1 and kept[0].text.endswith("success criteria")


def test_consolidate_dated_survive_even_when_listed_last() -> None:
    noise = [_cm(f"Do unrelated thing number {n} alpha{n}", f"q{n}") for n in range(7)]
    dated = _cm("Send SOC 2 report", "q-soc2", date(2026, 8, 20), who="Arjun")
    kept, merged, capped = ingest.consolidate_commitments([*noise, dated])
    assert kept[0] is dated and len(kept) == 5 and merged == 0 and capped == 3


def test_consolidate_merge_keeps_due_date_from_later_restatement() -> None:
    a = _cm("Send the ROI one-pager", "q1")
    b = _cm("Send the ROI one-pager", "q2", date(2026, 7, 30))
    kept, merged, _ = ingest.consolidate_commitments([a, b])
    assert merged == 1 and len(kept) == 1
    assert kept[0].due_date == date(2026, 7, 30) and kept[0].source_quote == "q2"


def test_consolidate_jaccard_and_distinct_deliverables() -> None:
    same = [
        _cm("Send the revised pricing deck with pilot option today", "q1"),
        _cm("Send revised pricing deck with the pilot option today", "q2", who="Arjun"),
    ]
    assert len(ingest.consolidate_commitments(same)[0]) == 1
    different = [_cm("Send the case study", "q1"), _cm("Send the ROI one-pager", "q2")]
    assert len(ingest.consolidate_commitments(different)[0]) == 2


async def test_run_ingest_applies_cap_and_keeps_planted_m4_deliverables(
    seeded: Session, factory: SessionFactory
) -> None:
    llm, memory = FakeLLM(), FakeMemoryService()
    ext = _extraction("m4_extraction.json").model_copy(update={"commitments": _noisy_m4()})
    llm.queue_response(ext)
    summary = await run_ingest(
        _job(seeded), "m4_finedge", llm=llm, memory=memory, session_factory=factory
    )
    rows = _commitments(seeded)
    assert len(rows) == 5 == summary.new_commitments
    deck, dag = _by_text(seeded, "pricing deck"), _by_text(seeded, "DAG configs")
    assert deck.due_date == date(2026, 9, 3) and dag.due_date == date(2026, 9, 5)


def test_p1_prompt_contains_exclusion_rules() -> None:
    text = render_prompt(
        "extract_meeting",
        our_company="Tracewise",
        our_people="Priya",
        meeting_title="T",
        meeting_date="2026-08-27",
        account_name="FinEdge",
        known_contacts="Karan",
        transcript="X",
    )
    for phrase in (
        "usually 1 to 3, at most 4",
        "Never pad",
        "Returning zero is correct",
        "recaps",
        "agendas",
        "attendee",
        "ONE commitment: bundle",
        "never use a quote that is only a question",
        "ONLY an explicit promise by a NAMED",
        "EXCLUDE all of these",
        "instructions to yourself",
        "hypotheticals",
        "vague follow-ups",
        "restatements of the same promise",
        "MERGE duplicates",
        "earliest source_quote",
    ):
        assert phrase in text


# ---- T12c: logistics filter and same-quote merge ----

PLANTED = [
    "Send the case study",  # M1
    "Send the ROI one-pager",  # M2
    "Send the SOC 2 report",  # M3
    "Send revised pricing deck with pilot option",  # M4
    "Send sample DAG configs",  # M4
    "Send the trust portal link and the pen-test summary",  # N2
    "Send the pen-test summary of the last engagement",  # N2
    "Send a value comparison against the current tool",  # O2
    "Share sandbox access for the trial",  # V2
    "Send a shortlist of candidate pipelines",  # M5
    "Send the security package and data-flow detail",
    "Send a recap deck with the pricing options",  # allow list wins over 'recap'
    "Prepare the migration plan",
    "Send the security questionnaire responses",
    "Confirm data residency in writing",
    "Confirm receipt of the executed copy and send the countersigned version",
    "Assign the security reviewer and send the questionnaire",
    "Prepare the quick-start guide",
    "Bring the architecture details for review",
    "Ask the team to document the checks they would keep or test",
    "Prepare vendor information and a concise scope outline",
    "Confirm what is included in the proposed onboarding",
    "Prepare a sanitized incident outline with timestamps and alert details",
    "Ask the team to document checks to keep or test",
    "Ask the team to document the checks they’d keep and want to test",
    "Confirm what expansion from a smaller initial pipeline scope would look like commercially",
]

LOGISTICS = [
    "Send a recap with the agenda, needed inputs, commercial questions, and decision timing",
    "Send a short technical-session outline explaining what the session will cover",
    "Send a short agenda with the integration questions",
    "Send a concise recap with owners and open questions",
    "Send a recap with the proposed agenda",
    "Bring a network diagram and explain the connection direction",
    "Send the attendee list",
    "Send a brief kickoff questionnaire",
    "Send a short security-session questionnaire",
    "Send a recap with the owners and dates",
    "Send a short note listing the information needed and the sections to be included",
    "Identify the Airflow and warehouse contacts for the technical session",
    "Send a calendar invite for the follow-up",
    "Share the meeting minutes",
]


@pytest.mark.parametrize("text", PLANTED)
def test_logistics_filter_keeps_planted_deliverables(text: str) -> None:
    assert not ingest.is_logistics(text)


@pytest.mark.parametrize("text", LOGISTICS)
def test_logistics_filter_drops_logistics(text: str) -> None:
    assert ingest.is_logistics(text)
    kept, dropped = ingest.filter_logistics([_cm(text, "q")])
    assert kept == [] and dropped == 1


def test_planted_deliverables_survive_consolidation_with_logistics_noise() -> None:
    planted = [_cm(t, f"planted quote {n}") for n, t in enumerate(PLANTED[:5])]
    noise = [_cm(t, f"noise quote {n}", date(2026, 8, 20)) for n, t in enumerate(LOGISTICS)]
    kept, _, _ = ingest.consolidate_commitments([*noise, *planted])
    assert [c.text for c in kept] == [c.text for c in planted]


def test_dated_logistics_does_not_outrank_undated_deliverable() -> None:
    recap = _cm("Send a recap with the agenda and decision timing", "q1", date(2026, 9, 1))
    deck = _cm("Send the revised pricing deck", "q2")
    kept, _, _ = ingest.consolidate_commitments([recap, deck])
    assert kept == [deck]


def test_same_quote_split_items_merge_into_one_bundled_commitment() -> None:
    quote = "I'll send the data-flow detail, access requirements, rollout outline, and the costs."
    split = [
        _cm("Send the data-flow detail", quote),
        _cm("Send the access requirements", quote, date(2026, 9, 5)),
        _cm("Send the data-flow detail, access requirements and rollout outline", quote),
    ]
    kept, merged, _ = ingest.consolidate_commitments(split)
    assert len(kept) == 1 and merged == 2
    assert kept[0].text == "Send the data-flow detail, access requirements and rollout outline"
    assert kept[0].due_date == date(2026, 9, 5)


async def test_run_ingest_drops_logistics_commitments(
    seeded: Session, factory: SessionFactory
) -> None:
    llm, memory = FakeLLM(), FakeMemoryService()
    recap = _cm(
        "Send a recap with the proposed agenda",
        "I'll also send a revised pricing deck with the pilot option by Sep 3.",
        date(2026, 9, 3),
    )
    base = _extraction("m4_extraction.json")
    llm.queue_response(base.model_copy(update={"commitments": [recap, *base.commitments]}))
    summary = await run_ingest(
        _job(seeded), "m4_finedge", llm=llm, memory=memory, session_factory=factory
    )
    assert summary.new_commitments == 2
    assert all("recap" not in c.text for c in _commitments(seeded))


# ---- T12e: retain timeout, safe error messages, P2 original words ----


def test_safe_error_message_redacts_secrets_and_truncates() -> None:
    raw = (
        "auth failed for sk-abcdef1234567890XYZ and gsk_AbCdEf123456 with "
        "Bearer eyJhbGciOi.secret.token and blob " + "A1b2C3d4" * 6 + " end"
    )
    msg = ingest.safe_error_message(RuntimeError(raw))
    for secret in ("sk-abcdef", "gsk_AbCd", "eyJhbGciOi", "A1b2C3d4A1b2"):
        assert secret not in msg
    assert "[redacted]" in msg and msg.endswith("end")
    long = ingest.safe_error_message(RuntimeError("x " * 500))
    assert len(long) == ingest.ERROR_MESSAGE_MAX_CHARS


@pytest.mark.parametrize(
    ("raw", "secret"),
    [
        ("call to https://api.x.com/v1?api_key=abcd1234efgh&x=1 failed", "abcd1234efgh"),
        ("bad org org-abc123def456 here", "abc123def456"),
        ("Authorization: Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
        ("key=abcdef0123456789abcd rejected", "abcdef0123456789abcd"),
        ("x-api-key: shortkey123", "shortkey123"),
        ("Authorization: abcdef", "abcdef"),
        ("bad key sk_live_abcdefghijklmnop", "abcdefghijklmnop"),
        ("bad key gsk-abc", "gsk-abc"),
        ("password=hunter2 nope", "hunter2"),
        ("https://h/x?access_token=zzz999&y=2", "zzz999"),
        ("Token abc.def.ghi expired", "abc.def.ghi"),
        ("Bad request. HTTP RESPONSE BODY: sk-verysecretvalue123", "verysecret"),
    ],
)
def test_safe_error_message_redacts_secret_shapes(raw: str, secret: str) -> None:
    assert secret not in ingest.safe_error_message(RuntimeError(raw))


@pytest.mark.parametrize(
    "benign", ["Retain timed out after 120s.", "LLM call exceeded the 120.0s timeout."]
)
def test_safe_error_message_leaves_benign_messages_unchanged(benign: str) -> None:
    assert ingest.safe_error_message(RuntimeError(benign)) == benign


def test_safe_error_message_cuts_response_bodies_and_never_empty() -> None:
    exc = RuntimeError('HTTP 400 Reason: Bad. HTTP response body: {"prompt": "TRANSCRIPT TEXT"}')
    msg = ingest.safe_error_message(exc)
    assert "TRANSCRIPT" not in msg and msg.startswith("HTTP 400")
    assert ingest.safe_error_message(RuntimeError("")) == "RuntimeError"
    assert "second" not in ingest.safe_error_message(RuntimeError("first\nsecond"))


async def test_ingest_passes_120s_retain_timeout(seeded: Session, factory: SessionFactory) -> None:
    memory = FakeMemoryService()
    await _ingest_m4(seeded, factory, FakeLLM(), memory)
    assert ingest.INGEST_RETAIN_TIMEOUT_S == 120.0
    assert memory.retain_timeouts == [120.0]


async def test_failed_job_stores_code_and_safe_message_done_job_does_not(
    seeded: Session, factory: SessionFactory
) -> None:
    llm = FakeLLM()
    llm.queue_error(MemoryUnavailableError("Retain timed out after 120s. key sk-abcdef1234567"))
    bad = _job(seeded)
    with pytest.raises(MemoryUnavailableError):
        await run_ingest(
            bad, "m4_finedge", llm=llm, memory=FakeMemoryService(), session_factory=factory
        )
    seeded.expire_all()
    job = repo.get_job(seeded, bad)
    assert job is not None and job.error == "memory_unavailable"
    assert job.result is not None
    assert job.result["error_code"] == "memory_unavailable"
    assert job.result["error_message"].startswith("Retain timed out after 120s.")
    assert "sk-abcdef" not in job.result["error_message"]

    good = await _ingest_m4(seeded, factory, FakeLLM(), FakeMemoryService())
    seeded.expire_all()
    ok = repo.get_job(seeded, good)
    assert ok is not None and ok.error is None and ok.result is not None
    assert "error_code" not in ok.result and "new_commitments" in ok.result


async def test_p2_prompt_lists_original_words_and_roi_one_pager_case(
    seeded: Session, factory: SessionFactory
) -> None:
    text = "Prepare a decision-oriented comparison of the current approach and proposed scope"
    ingest_repo.create_commitment_rows(
        seeded,
        account_id="acc_finedge",
        meeting_id="m4_finedge",
        rows=[
            (Owner.us, "c_priya", text, date(2026, 8, 5), "I'll send the ROI one-pager by Aug 5")
        ],
    )
    cm_id = _commitments(seeded)[0].id
    llm = FakeLLM()
    llm.queue_response(
        MeetingExtraction(
            people=[],
            commitments=[],
            facts=[],
            deal_budget_usd=None,
            acknowledgements=[
                Acknowledgement(
                    description="ROI one-pager received",
                    source_quote="thanks for sending the DAG configs",
                )
            ],
        )
    )
    llm.queue_response(
        AckMatches(closed=[ClosedMatch(commitment_id=cm_id, acknowledgement_index=0)])
    )
    summary = await run_ingest(
        _job(seeded), "m5_finedge", llm=llm, memory=FakeMemoryService(), session_factory=factory
    )
    prompt = llm.calls[-1].prompt
    assert f"{cm_id}: {text}" in prompt
    assert '| original words: "I\'ll send the ROI one-pager by Aug 5"' in prompt
    assert "different words than the commitment's text" in prompt
    assert '{"closed": []}' in prompt
    assert summary.closed_commitments == 1


def test_p2_original_words_are_truncated_to_200_chars() -> None:
    c = Commitment(
        id="cm_x",
        account_id="a",
        meeting_id="m",
        owner=Owner.us,
        text="T",
        source_quote="w " * 300,
        status=CommitmentStatus.open,
    )
    line = ingest._format_open_commitment(c)
    quote = line.split('original words: "', 1)[1].rstrip('"')
    assert len(quote) <= ingest.MAX_QUOTE_CHARS


async def test_non_receipt_complaint_cannot_close_via_unknown_id(
    seeded: Session, factory: SessionFactory
) -> None:
    llm, memory = FakeLLM(), FakeMemoryService()
    await _ingest_m4(seeded, factory, llm, memory)
    llm.queue_response(_extraction("m5_extraction.json"))
    llm.queue_response(
        AckMatches(closed=[ClosedMatch(commitment_id="cm_madeup", acknowledgement_index=1)])
    )
    summary = await run_ingest(
        _job(seeded), "m5_finedge", llm=llm, memory=memory, session_factory=factory
    )
    assert summary.closed_commitments == 0
    assert all(c.status == CommitmentStatus.open for c in _commitments(seeded))


# ---- T12f: merged/bundled commitment keeps the quote that carries the date or deliverable ----

COMPARISON = (
    "Understood. I'll make it a decision-oriented comparison: current approach, proposed "
    "scope, costs, and what we can or can't credibly quantify."
)
ROI = (
    "I'll send an ROI one-pager by Aug 5. I'll keep it provisional until we have the "
    "incident and maintenance inputs from Karan's team."
)
M2_TRANSCRIPT = "\n".join(
    [
        "[2026-07-28T09:15:26+05:30] Priya Nair (Account Executive, Tracewise): " + COMPARISON,
        "[2026-07-28T09:16:02+05:30] Karan Shah (Data Platform Lead, FinEdge Payments): "
        "I can get the incident data over by Aug 5 as well, the scope is clear.",
        "[2026-07-28T09:40:12+05:30] Priya Nair (Account Executive, Tracewise): " + ROI,
    ]
)
M3_TRANSCRIPT = (
    "[2026-08-12T10:05:00+05:30] Rahul Mehta (VP Engineering, FinEdge Payments): "
    "Yes, I received the ROI one-pager. Thanks."
)
BUNDLED_TEXT = (
    "Prepare a decision-oriented comparison of the current approach and proposed scope, "
    "including costs and what can be credibly quantified."
)


def _bundled(quote: str = COMPARISON, due: date | None = date(2026, 8, 5)) -> ExtractedCommitment:
    return _cm(BUNDLED_TEXT, quote, due)


def test_refine_replaces_quote_with_same_speaker_sentence_carrying_the_date() -> None:
    (out,), refined = ingest.refine_quotes([_bundled()], M2_TRANSCRIPT)
    assert refined == 1 and out.source_quote == ROI
    assert (out.text, out.due_date, out.owner, out.owner_person) == (
        BUNDLED_TEXT,
        date(2026, 8, 5),
        Owner.us,
        "Priya",
    )
    assert is_verbatim(out.source_quote, normalize_text(M2_TRANSCRIPT))


@pytest.mark.parametrize(
    "quote",
    [
        "I'll send it by Aug 5 for sure",
        "due August 5th",
        "by 2026-08-05",
        "by the 5th",
        "I'll send it by Friday",
        "let's do it next week",
    ],
)
def test_refine_leaves_quotes_that_already_carry_a_date_signal(quote: str) -> None:
    item = _bundled(quote)
    assert ingest.refine_quotes([item], M2_TRANSCRIPT) == ([item], 0)


def test_refine_never_touches_undated_commitments() -> None:
    item = _bundled(due=None)
    assert ingest.refine_quotes([item], M2_TRANSCRIPT) == ([item], 0)


def test_refine_keeps_quote_when_no_same_speaker_sentence_qualifies() -> None:
    transcript = M2_TRANSCRIPT.replace("by Aug 5. I'll keep", "soon. I'll keep")
    item = _bundled()
    # Karan's "by Aug 5" sentence is a different speaker, so it must not be used.
    assert ingest.refine_quotes([item], transcript) == ([item], 0)


def test_refine_requires_deliverable_term_or_shared_content_word() -> None:
    transcript = (
        "[2026-07-28T09:15:26+05:30] Priya Nair (Account Executive, Tracewise): "
        + COMPARISON
        + "\n[2026-07-28T09:40:12+05:30] Priya Nair (Account Executive, Tracewise): "
        "Lunch is booked for Aug 5 at noon."
    )
    item = _bundled()
    assert ingest.refine_quotes([item], transcript) == ([item], 0)


def test_refine_does_not_use_a_different_speakers_sentence() -> None:
    karan_only = "\n".join(
        [
            "[2026-07-28T09:15:26+05:30] Priya Nair (Account Executive, Tracewise): " + COMPARISON,
            "[2026-07-28T09:40:12+05:30] Karan Shah (Data Platform Lead, FinEdge): " + ROI,
        ]
    )
    item = _bundled()
    assert ingest.refine_quotes([item], karan_only) == ([item], 0)


def test_refine_clips_long_utterance_to_the_dated_sentence() -> None:
    filler = "We will keep the comparison provisional and detailed. " * 6
    text = filler + "I'll send an ROI one-pager by Aug 5. " + filler
    transcript = (
        "[2026-07-28T09:15:26+05:30] Priya Nair (Account Executive, Tracewise): "
        + COMPARISON
        + "\n[2026-07-28T09:40:12+05:30] Priya Nair (Account Executive, Tracewise): "
        + text
    )
    (out,), refined = ingest.refine_quotes([_bundled()], transcript)
    assert refined == 1 and out.source_quote == "I'll send an ROI one-pager by Aug 5."
    assert len(out.source_quote) <= ingest.MAX_QUOTE_CHARS


def test_merge_keeps_the_quote_of_the_member_carrying_the_due_date() -> None:
    norm = normalize_text(M2_TRANSCRIPT)
    comparison = _cm("Prepare a decision-oriented comparison of scope and costs", COMPARISON)
    dated = _cm(
        "Prepare a decision-oriented comparison of scope and costs and the ROI one-pager",
        ROI,
        date(2026, 8, 5),
    )
    for order in ([comparison, dated], [dated, comparison]):
        (out,), merged, _ = ingest.consolidate_commitments(order, norm)
        assert merged == 1 and out.source_quote == ROI and out.due_date == date(2026, 8, 5)
        assert out.text.endswith("the ROI one-pager")  # most specific (longer) text kept


def test_merge_without_dates_prefers_the_quote_naming_the_deliverable() -> None:
    norm = normalize_text(M2_TRANSCRIPT)
    vague = _cm("Send the ROI one-pager", "Understood.")
    named = _cm("Send the ROI one-pager", ROI)
    (out,), merged, _ = ingest.consolidate_commitments([vague, named], norm)
    assert merged == 1 and out.source_quote == ROI


async def _add_meeting(
    db: Session, meeting_id: str, when: datetime, title: str, transcript: str, who: list[str]
) -> None:
    repo.create_meeting(
        db,
        Meeting(
            id=meeting_id,
            account_id="acc_finedge",
            title=title,
            scheduled_at=when,
            status="upcoming",
            transcript=transcript,
        ),
    )
    for cid in who:
        repo.add_attendee(db, meeting_id, cid)


async def test_m2_case_end_to_end_quote_is_refined_and_p2_sees_roi_one_pager(
    seeded: Session, factory: SessionFactory
) -> None:
    await _add_meeting(
        seeded,
        "m2_finedge",
        datetime(2026, 7, 28, 9, tzinfo=UTC),
        "Budget",
        M2_TRANSCRIPT,
        ["c_priya", "c_karan"],
    )
    await _add_meeting(
        seeded,
        "m3_finedge",
        datetime(2026, 8, 12, 10, tzinfo=UTC),
        "Deep dive",
        M3_TRANSCRIPT,
        ["c_priya", "c_rahul"],
    )
    llm, memory = FakeLLM(), FakeMemoryService()
    llm.queue_response(
        MeetingExtraction(
            people=[],
            acknowledgements=[],
            facts=[],
            deal_budget_usd=None,
            commitments=[_bundled()],
        )
    )
    await run_ingest(_job(seeded), "m2_finedge", llm=llm, memory=memory, session_factory=factory)
    (row,) = [c for c in _commitments(seeded) if c.meeting_id == "m2_finedge"]
    assert row.source_quote == ROI
    assert (row.text, row.due_date, row.owner) == (BUNDLED_TEXT, date(2026, 8, 5), Owner.us)

    llm.queue_response(
        MeetingExtraction(
            people=[],
            commitments=[],
            facts=[],
            deal_budget_usd=None,
            acknowledgements=[
                Acknowledgement(
                    description="ROI one-pager received",
                    source_quote="Yes, I received the ROI one-pager.",
                )
            ],
        )
    )
    llm.queue_response(
        AckMatches(closed=[ClosedMatch(commitment_id=row.id, acknowledgement_index=0)])
    )
    summary = await run_ingest(
        _job(seeded), "m3_finedge", llm=llm, memory=memory, session_factory=factory
    )
    p2_prompt = llm.calls[-1].prompt
    line = next(ln for ln in p2_prompt.splitlines() if ln.startswith(row.id))
    assert "original words:" in line and "ROI one-pager by Aug 5" in line
    assert summary.closed_commitments == 1


def _two_line_transcript(*lines: tuple[str, str]) -> str:
    return "\n".join(
        f"[2026-07-28T09:{n:02d}:00+05:30] {speaker} (Account Executive, Tracewise): {text}"
        for n, (speaker, text) in enumerate(lines, start=10)
    )


def test_refine_skips_questions_verifier_case() -> None:
    transcript = _two_line_transcript(
        ("Priya Nair", "I will draft the comparison for you."),
        ("Priya Nair", "Should I send the pricing sheet by Aug 5?"),
        ("Priya Nair", "I will also send the security report by Aug 5."),
    )
    item = _cm("Draft the comparison", "I will draft the comparison for you.", date(2026, 8, 5))
    (out,), refined = ingest.refine_quotes([item], transcript)
    assert "?" not in out.source_quote
    assert out.source_quote == "I will also send the security report by Aug 5." and refined == 1


def test_refine_with_only_a_question_keeps_the_original_quote() -> None:
    transcript = _two_line_transcript(
        ("Priya Nair", "I will draft the comparison for you."),
        ("Priya Nair", "Should I send the comparison by Aug 5?"),
    )
    item = _cm("Draft the comparison", "I will draft the comparison for you.", date(2026, 8, 5))
    assert ingest.refine_quotes([item], transcript) == ([item], 0)


def test_refine_prefers_shared_content_word_over_deliverable_term_only() -> None:
    transcript = _two_line_transcript(
        ("Priya Nair", "I will draft the comparison for you."),
        ("Priya Nair", "I will send the security report by Aug 5."),  # deliverable term only
        ("Priya Nair", "The comparison will follow by Aug 5."),  # shares 'comparison'
    )
    item = _cm("Draft the comparison", "I will draft the comparison for you.", date(2026, 8, 5))
    (out,), _ = ingest.refine_quotes([item], transcript)
    assert out.source_quote == "The comparison will follow by Aug 5."


def test_refine_among_equal_candidates_keeps_the_earliest() -> None:
    transcript = _two_line_transcript(
        ("Priya Nair", "I will draft the comparison for you."),
        ("Priya Nair", "The comparison is due Aug 5."),
        ("Priya Nair", "Again, the comparison lands Aug 5."),
    )
    item = _cm("Draft the comparison", "I will draft the comparison for you.", date(2026, 8, 5))
    (out,), _ = ingest.refine_quotes([item], transcript)
    assert out.source_quote == "The comparison is due Aug 5."
