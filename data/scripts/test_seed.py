"""Seed script (T11): setup, ingest order, resume, stop-on-failure, log lines, sanity report.

Everything runs on a tmp-path SQLite file with FakeMemoryService and an injected fake ingest
function. No network, no LLM, never the real app.db.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from datetime import UTC, date
from pathlib import Path
from typing import Any

import pytest
from seed import (
    CHAIN,
    EXCLUDED_FROM_INGEST,
    SeedFailure,
    SeedResult,
    resolve_db_path,
    seed,
)
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine, select
from validate import SEED_DIR, TRANSCRIPTS_DIR, load_seed, read_transcripts

from app.core.errors import LLMTimeoutError
from app.core.time import today
from app.db import ingest_repo
from app.db import repository as repo
from app.db.models import Account, Contact, Job, Meeting, MeetingAttendee
from app.llm.client import LLMClient
from app.schemas.api import LearnedSummary
from app.schemas.enums import Owner
from app.services.ingest import SessionFactory
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fake_memory_service import FakeMemoryService

SEED = load_seed(SEED_DIR)
TRANSCRIPTS = read_transcripts(SEED, TRANSCRIPTS_DIR)
DONE_IDS = [m["id"] for m in SEED.meetings if m["id"] not in EXCLUDED_FROM_INGEST]
ORDER = [
    m["id"]
    for m in sorted(
        (m for m in SEED.meetings if m["id"] in DONE_IDS), key=lambda m: (m["date"], m["id"])
    )
]

DECK = ("Send the revised pricing deck with the pilot option", date(2026, 9, 3))

Scripted = dict[str, list[tuple[str, date | None, bool]]]


class RecordingMemory(FakeMemoryService):
    """FakeMemoryService that records the order of gateway calls and can report 'busy'."""

    def __init__(self, busy_on_call: int | None = None) -> None:
        super().__init__()
        self.events: list[str] = []
        self.mental_model_accounts: list[tuple[str, str]] = []
        self._idle_calls = 0
        self._busy_on_call = busy_on_call

    async def ensure_bank(self) -> None:
        self.events.append("ensure_bank")
        await super().ensure_bank()

    async def wait_until_idle(self, timeout_s: float = 60.0) -> bool:
        self._idle_calls += 1
        self.events.append(f"idle:{timeout_s:g}")
        return self._idle_calls != self._busy_on_call

    async def ensure_mental_models(self, accounts: Any) -> None:
        self.events.append("mental_models")
        self.mental_model_accounts = list(accounts)
        await super().ensure_mental_models(accounts)


class FakeIngest:
    """Stands in for `run_ingest`: records calls, writes the ledger rows a real run would."""

    def __init__(
        self,
        commitments: Scripted | None = None,
        fail_on: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.calls: list[str] = []
        self.jobs: list[str] = []
        self.commitments: Scripted = commitments or {}
        self.fail_on = fail_on
        self.error = error or LLMTimeoutError("took too long")

    async def __call__(
        self,
        job_id: str,
        meeting_id: str,
        *,
        llm: LLMClient,
        memory: Any,
        session_factory: SessionFactory,
    ) -> LearnedSummary:
        self.calls.append(meeting_id)
        self.jobs.append(job_id)
        if meeting_id == self.fail_on:
            with session_factory() as session:
                ingest_repo.finish_job(session, job_id, error=getattr(self.error, "code", "x"))
            raise self.error
        scripted = self.commitments.get(meeting_id, [])
        with session_factory() as session:
            meeting = repo.get_meeting(session, meeting_id)
            assert meeting is not None and meeting.transcript
            rows = [(Owner.us, None, text, due, "quote") for text, due, _ in scripted]
            created = ingest_repo.create_commitment_rows(
                session, account_id=meeting.account_id, meeting_id=meeting_id, rows=rows
            )
            for row, (_, _, done) in zip(created, scripted, strict=True):
                if done:
                    repo.close_commitment(session, row.id, closed_by_meeting_id=meeting_id)
            ingest_repo.set_meeting_ingested(session, meeting_id, ingest_repo.stamp())
            summary = LearnedSummary(
                facts=["a", "b"], new_commitments=len(created), closed_commitments=0, alerts=[]
            )
            ingest_repo.finish_job(session, job_id, result=summary.model_dump(mode="json"))
        return summary


def healthy_commitments(*, deck_open: bool = True) -> Scripted:
    """A ledger where every promise in CHAIN is done, plus the M4 deck (open by default)."""
    return {
        "m1_finedge": [("Send the case study", date(2026, 7, 17), True)],
        "m2_finedge": [("Send an ROI one-pager", date(2026, 8, 4), True)],
        "m3_finedge": [("Share the SOC 2 report under NDA", date(2026, 8, 19), True)],
        "m4_finedge": [
            ("Send the DAG configs", date(2026, 9, 1), True),
            (DECK[0], DECK[1], not deck_open),
        ],
        "o2_orbit": [("Send the value comparison", date(2026, 6, 25), True)],
        "n2_nimbus": [("Share the trust portal link", date(2026, 3, 28), True)],
        "v2_veda": [("Set up the sandbox", date(2026, 9, 17), True)],
    }


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    eng = create_engine(
        f"sqlite:///{tmp_path / 'seed.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def factory(engine: Engine) -> SessionFactory:
    def make() -> AbstractContextManager[Session]:
        return Session(engine)

    return make


class Lines(list[str]):
    def __call__(self, line: str) -> None:
        self.append(line)


def run_seed(
    factory: SessionFactory,
    ingest_fn: Callable[..., Any],
    memory: FakeMemoryService | None = None,
    log: Lines | None = None,
    transcripts: dict[str, str] | None = None,
    **kwargs: Any,
) -> SeedResult:
    return asyncio.run(
        seed(
            ingest_fn=ingest_fn,
            memory=memory or RecordingMemory(),
            llm=FakeLLM(),
            session_factory=factory,
            seed_data=SEED,
            transcripts=transcripts if transcripts is not None else TRANSCRIPTS,
            log=log if log is not None else Lines(),
            **kwargs,
        )
    )


# ---- setup ----


def test_seed_data_shape() -> None:
    assert len(ORDER) == 15
    assert EXCLUDED_FROM_INGEST == {"m6_finedge", "v4_veda"}


def test_inserts_all_17_meetings_and_ingests_15(factory: SessionFactory) -> None:
    ingest = FakeIngest(healthy_commitments())
    run_seed(factory, ingest)
    with factory() as s:
        meetings = {m.id: m for m in s.exec(select(Meeting)).all()}
        assert len(meetings) == 17
        assert meetings["m6_finedge"].status == "upcoming"
        assert meetings["v4_veda"].status == "upcoming"
        assert meetings["m6_finedge"].ingested_at is None
        assert meetings["m6_finedge"].transcript is None
        assert all(meetings[i].status == "done" and meetings[i].ingested_at for i in DONE_IDS)
        assert len(s.exec(select(Account)).all()) == 4
        assert len(s.exec(select(Contact)).all()) == len(SEED.contacts)
    assert sorted(ingest.calls) == sorted(DONE_IDS)


def test_accounts_contacts_and_attendees_from_seed(factory: SessionFactory) -> None:
    run_seed(factory, FakeIngest(healthy_commitments()))
    with factory() as s:
        acc = repo.get_account(s, "acc_finedge")
        assert acc is not None and acc.deal_value_usd == 40000 and acc.stage == "evaluation"
        priya = repo.get_contact(s, "c_priya")
        assert priya is not None and priya.account_id is None and priya.role
        karan = repo.get_contact(s, "c_karan")
        assert karan is not None and karan.account_id == "acc_finedge"
        for m in SEED.meetings:
            got = {a.contact_id for a in repo.list_attendees_for_meeting(s, m["id"])}
            assert got == set(m["attendees"])


def test_scheduled_at_is_midday_utc_on_the_seed_date(factory: SessionFactory) -> None:
    run_seed(factory, FakeIngest(healthy_commitments()))
    with factory() as s:
        for m in SEED.meetings:
            row = repo.get_meeting(s, m["id"])
            assert row is not None
            assert row.scheduled_at.date() == date.fromisoformat(m["date"]), m["id"]
            assert row.scheduled_at.hour == 12
            if row.scheduled_at.tzinfo is not None:
                assert row.scheduled_at.utcoffset() == UTC.utcoffset(None)


def test_transcripts_mapped_to_the_right_meeting_ids(factory: SessionFactory) -> None:
    run_seed(factory, FakeIngest(healthy_commitments()))
    with factory() as s:
        for meeting_id in DONE_IDS:
            row = repo.get_meeting(s, meeting_id)
            assert row is not None and row.transcript == TRANSCRIPTS[meeting_id]
        v4 = repo.get_meeting(s, "v4_veda")
        assert v4 is not None and v4.transcript is None


# ---- ingest order ----


def test_ingest_is_in_global_date_order(factory: SessionFactory) -> None:
    ingest = FakeIngest(healthy_commitments())
    run_seed(factory, ingest)
    assert ingest.calls == ORDER
    assert ingest.calls[0] == "n1_nimbus"  # 2026-03-10 is the earliest meeting of all
    dates = [SEED.meeting(i)["date"] for i in ingest.calls]
    assert dates == sorted(dates)


def test_each_meeting_gets_its_own_job_id(factory: SessionFactory) -> None:
    ingest = FakeIngest(healthy_commitments())
    run_seed(factory, ingest)
    assert len(set(ingest.jobs)) == 15
    assert all(re.fullmatch(r"job_[0-9a-f]{8}", j) for j in ingest.jobs)
    with factory() as s:
        assert {j.status for j in s.exec(select(Job)).all()} == {"done"}


def test_memory_calls_order_and_idle_waits(factory: SessionFactory) -> None:
    memory = RecordingMemory()
    run_seed(factory, FakeIngest(healthy_commitments()), memory=memory, idle_timeout_s=180)
    ev = memory.events
    assert ev[0] == "ensure_bank"
    assert ev.count("idle:180") == 17  # after each of 15, once after all, once after models
    assert ev.count("mental_models") == 1
    assert ev[-3:] == ["idle:180", "mental_models", "idle:180"]
    assert sorted(a for a, _ in memory.mental_model_accounts) == sorted(
        a["id"] for a in SEED.accounts
    )
    assert dict(memory.mental_model_accounts)["acc_finedge"] == "FinEdge Payments"


def test_idle_wait_follows_every_meeting_before_the_next_starts(factory: SessionFactory) -> None:
    order: list[str] = []
    memory = RecordingMemory()
    real_idle = memory.wait_until_idle

    async def idle(timeout_s: float = 60.0) -> bool:
        order.append("idle")
        return await real_idle(timeout_s)

    memory.wait_until_idle = idle  # type: ignore[method-assign]
    inner = FakeIngest(healthy_commitments())

    async def tracked(*a: Any, **k: Any) -> LearnedSummary:
        order.append("ingest")
        return await inner(*a, **k)

    run_seed(factory, tracked, memory=memory)
    assert order[:4] == ["ingest", "idle", "ingest", "idle"]


# ---- resume and failure ----


def test_stops_at_first_failure_and_reports_meeting_and_code(factory: SessionFactory) -> None:
    ingest = FakeIngest(healthy_commitments(), fail_on=ORDER[3])
    memory = RecordingMemory()
    log = Lines()
    with pytest.raises(SeedFailure) as info:
        run_seed(factory, ingest, memory=memory, log=log)
    assert info.value.meeting_id == ORDER[3]
    assert info.value.code == "llm_timeout"
    assert ingest.calls == ORDER[:4]
    assert "mental_models" not in memory.events
    assert re.search(rf"\[04/15\] {ORDER[3]} FAILED llm_timeout after \d+\.\ds", "\n".join(log))


def test_resume_skips_done_meetings_and_creates_no_duplicates(factory: SessionFactory) -> None:
    first = FakeIngest(healthy_commitments(), fail_on=ORDER[3])
    with pytest.raises(SeedFailure):
        run_seed(factory, first)
    second = FakeIngest(healthy_commitments())
    log = Lines()
    run_seed(factory, second, log=log)
    assert second.calls == ORDER[3:]  # the failed one is retried, the 3 done are skipped
    for meeting_id in ORDER[:3]:
        assert any(f"{meeting_id} skip" in line for line in log)
    with factory() as s:
        assert len(s.exec(select(Meeting)).all()) == 17
        assert len(s.exec(select(Account)).all()) == 4
        assert len(s.exec(select(Contact)).all()) == len(SEED.contacts)
        assert len(s.exec(select(MeetingAttendee)).all()) == sum(
            len(m["attendees"]) for m in SEED.meetings
        )
        failed = [j for j in s.exec(select(Job)).all() if j.status == "failed"]
        assert len(failed) == 1


def test_setup_does_not_overwrite_existing_rows(factory: SessionFactory) -> None:
    with pytest.raises(SeedFailure):
        run_seed(factory, FakeIngest(healthy_commitments(), fail_on=ORDER[0]))
    with factory() as s:
        ingest_repo.update_account_deal_value(s, "acc_finedge", 75000)
    run_seed(factory, FakeIngest(healthy_commitments()))
    with factory() as s:
        acc = repo.get_account(s, "acc_finedge")
        assert acc is not None and acc.deal_value_usd == 75000


def test_done_status_without_ingested_at_is_retried(factory: SessionFactory) -> None:
    run_seed(factory, FakeIngest(healthy_commitments()))
    with factory() as s:
        row = repo.get_meeting(s, ORDER[5])
        assert row is not None
        row.ingested_at = None
        s.add(row)
        s.commit()
    again = FakeIngest({})
    run_seed(factory, again)
    assert again.calls == [ORDER[5]]


def test_wait_until_idle_false_stops_the_run(factory: SessionFactory) -> None:
    ingest = FakeIngest(healthy_commitments())
    memory = RecordingMemory(busy_on_call=2)
    with pytest.raises(SeedFailure) as info:
        run_seed(factory, ingest, memory=memory)
    assert info.value.code == "memory_not_idle"
    assert info.value.meeting_id == ORDER[1]
    assert ingest.calls == ORDER[:2]
    assert "mental_models" not in memory.events


def test_final_wait_false_stops_before_mental_models(factory: SessionFactory) -> None:
    memory = RecordingMemory(busy_on_call=16)
    with pytest.raises(SeedFailure) as info:
        run_seed(factory, FakeIngest(healthy_commitments()), memory=memory)
    assert info.value.code == "memory_not_idle"
    assert "mental_models" not in memory.events


def test_missing_transcript_is_a_failure(factory: SessionFactory) -> None:
    partial = {k: v for k, v in TRANSCRIPTS.items() if k != "m3_finedge"}
    ingest = FakeIngest(healthy_commitments())
    with pytest.raises(SeedFailure) as info:
        run_seed(factory, ingest, transcripts=partial)
    assert info.value.meeting_id == "m3_finedge"
    assert "m3_finedge" not in ingest.calls


# ---- progress log ----


def test_progress_lines_have_start_time_duration_and_counts(factory: SessionFactory) -> None:
    log = Lines()
    run_seed(factory, FakeIngest(healthy_commitments()), log=log)
    first = ORDER[0]
    start = [line for line in log if f"{first} start" in line]
    assert len(start) == 1
    assert re.fullmatch(
        rf"\[01/15\] {SEED.meeting(first)['date']} {first} start \d\d:\d\d:\d\d", start[0]
    )
    done = [line for line in log if f"[01/15] {first} done" in line]
    assert re.fullmatch(
        rf"\[01/15\] {first} done in \d+\.\ds \(new commitments \d+, closed \d+, facts \d+\)",
        done[0],
    )
    assert sum(1 for line in log if " start " in line) == 15
    assert sum(1 for line in log if " done in " in line) == 15
    assert log.index(start[0]) < log.index(done[0])


def test_log_never_contains_transcript_text(factory: SessionFactory) -> None:
    log = Lines()
    run_seed(factory, FakeIngest(healthy_commitments()), log=log)
    blob = "\n".join(log)
    assert TRANSCRIPTS["m1_finedge"].splitlines()[3] not in blob


# ---- sanity report ----


def test_sanity_ok_when_deck_open_overdue_and_chain_done(factory: SessionFactory) -> None:
    result = run_seed(factory, FakeIngest(healthy_commitments()))
    assert result.ok, result.problems
    assert result.deck_open_overdue
    assert today() == date(2026, 9, 28)
    assert len(result.chain_done) == len(CHAIN)


def test_sanity_fails_when_deck_is_closed(factory: SessionFactory) -> None:
    result = run_seed(factory, FakeIngest(healthy_commitments(deck_open=False)))
    assert not result.ok
    assert not result.deck_open_overdue
    assert any("pricing deck" in p.lower() for p in result.problems)


def test_sanity_fails_when_a_chain_promise_is_not_done(factory: SessionFactory) -> None:
    commitments = healthy_commitments()
    commitments["v2_veda"] = [("Set up the sandbox", date(2026, 9, 17), False)]
    result = run_seed(factory, FakeIngest(commitments))
    assert not result.ok
    assert any("sandbox" in p.lower() for p in result.problems)


def test_sanity_fails_when_deck_due_date_is_wrong(factory: SessionFactory) -> None:
    commitments = healthy_commitments()
    commitments["m4_finedge"][1] = (DECK[0], date(2026, 9, 10), False)
    result = run_seed(factory, FakeIngest(commitments))
    assert not result.ok


# ---- db path ----


def test_resolve_db_path_relative_and_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert resolve_db_path("sqlite:///./app.db") == tmp_path / "app.db"
    assert resolve_db_path("sqlite:///app.db") == tmp_path / "app.db"
    assert resolve_db_path(f"sqlite:///{tmp_path}/x.db") == tmp_path / "x.db"
    with pytest.raises(ValueError):
        resolve_db_path("postgresql://u@h/db")
    with pytest.raises(ValueError):
        resolve_db_path("sqlite://")
