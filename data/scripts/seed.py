"""Seed script (ticket T11): loads the synthetic data through the REAL ingest path.

Usage (cwd must be backend/ so the relative SQLite path resolves to backend/app.db):
    cd backend && uv run python ../data/scripts/seed.py [--log-file PATH] [--idle-timeout SECONDS]

What it does, in order (docs/hindsight-integration.md "Seed order"):
1. setup, idempotent and create-if-missing (it never deletes or overwrites): tables, the
   memory bank, Accounts, Contacts (ours and theirs), all 17 Meetings and their attendees;
2. ingests the 15 seeded transcripts one at a time in GLOBAL date order (ties by id), through
   the same in-process `run_ingest` the API's background task uses, waiting for Hindsight to go
   idle after each meeting so the next one sees processed memory;
3. once all are in: waits for idle, `ensure_mental_models`, waits again (mental models are built
   by Hindsight after creation; `memory_service` has no explicit refresh call, so none is made);
4. prints a sanity report (open/done commitments per account, the M4 pricing deck must be open
   and overdue, the promise chain must be done). This report is a check, not the acceptance gate.

Resumable: a meeting is done when `status == "done"` and `ingested_at` is set; such meetings are
skipped on a re-run. The run stops at the FIRST failure (typed error, LLM timeout, or Hindsight
not going idle) and exits non-zero; re-running continues from there. No silent retries.

Meeting rows store `scheduled_at` as 12:00 UTC on the seed date, so `.date()` is the seed date
in UTC and in IST. Meetings with transcripts start as `upcoming` and become `done` only when
`run_ingest` finishes them, so a half-seeded DB never shows un-ingested meetings as done.

Exit codes: 0 ok, 1 failure (see the last log line), 2 ingest finished but the sanity report failed.
Transcripts and keys are never logged. Nothing here runs at import time.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent.parent / "backend"
for _p in (_HERE, _BACKEND):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from sqlalchemy.engine import make_url  # noqa: E402
from validate import SEED_DIR, TRANSCRIPTS_DIR, Seed, load_seed, read_transcripts  # noqa: E402

from app.core.errors import AppError  # noqa: E402
from app.core.time import today  # noqa: E402
from app.db import ingest_repo, meetings_repo  # noqa: E402
from app.db import repository as repo  # noqa: E402
from app.db.models import Account, Contact, Meeting  # noqa: E402
from app.llm.client import LLMClient  # noqa: E402
from app.memory.memory_service import MemoryService  # noqa: E402
from app.schemas.api import LearnedSummary  # noqa: E402
from app.schemas.enums import CommitmentStatus  # noqa: E402
from app.services.ingest import SessionFactory, run_ingest  # noqa: E402

WAIT_IDLE_SECONDS = 180
DEFAULT_LOG_NAME = "seed.log"
# The live-demo meeting and the next upcoming one: seeded as rows, never ingested.
EXCLUDED_FROM_INGEST = {"m6_finedge", "v4_veda"}

DECK_MEETING_ID = "m4_finedge"
DECK_ACCOUNT_ID = "acc_finedge"
DECK_KEYWORD = re.compile(r"pricing deck", re.IGNORECASE)
DECK_DUE = date(2026, 9, 3)

# The promise chain the demo relies on. Keywords live only here; matching is lenient (any
# commitment on that account whose text matches and that is done counts).
CHAIN: list[tuple[str, str, re.Pattern[str]]] = [
    ("m1 case study", "acc_finedge", re.compile(r"case study", re.IGNORECASE)),
    ("m2 ROI one-pager", "acc_finedge", re.compile(r"\broi\b|one[- ]?pager", re.IGNORECASE)),
    ("m3 SOC 2 report", "acc_finedge", re.compile(r"soc ?2", re.IGNORECASE)),
    ("m4 DAG configs", "acc_finedge", re.compile(r"\bdags?\b", re.IGNORECASE)),
    ("o2 value comparison", "acc_orbit", re.compile(r"comparison", re.IGNORECASE)),
    ("n2 trust portal", "acc_nimbus", re.compile(r"trust portal", re.IGNORECASE)),
    ("v2 sandbox", "acc_veda", re.compile(r"sandbox", re.IGNORECASE)),
]

Log = Callable[[str], None]
IngestFn = Callable[..., Awaitable[LearnedSummary]]


class SeedFailure(Exception):
    """The run stopped: `code` is the typed error code, `meeting_id` where it stopped."""

    def __init__(self, meeting_id: str, code: str, message: str = "") -> None:
        super().__init__(f"{meeting_id}: {code} {message}".strip())
        self.meeting_id = meeting_id
        self.code = code


@dataclass
class SeedResult:
    ingested: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    deck_open_overdue: bool = False
    chain_done: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


class ProgressLog:
    """Prints each line immediately and appends it to the log file (both flushed)."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, line: str) -> None:
        print(line, flush=True)
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()


def resolve_db_path(database_url: str, cwd: Path | None = None) -> Path:
    """Absolute SQLite file path for `settings.database_url` (relative paths use the cwd)."""
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        raise ValueError("Only file-based sqlite database URLs are supported.")
    path = Path(url.database)
    if not path.is_absolute():
        path = (cwd or Path.cwd()) / path
    return Path(str(path.resolve()))


def _clock() -> str:
    return time.strftime("%H:%M:%S")  # real wall clock, for log lines only


def _scheduled_at(day: str) -> datetime:
    parsed = date.fromisoformat(day)
    return datetime(parsed.year, parsed.month, parsed.day, 12, 0, tzinfo=UTC)


# ---- setup ----


def _setup(session_factory: SessionFactory, data: Seed) -> None:
    """Create-if-missing accounts, contacts, meetings and attendees. Never updates or deletes."""
    with session_factory() as session:
        for acc in data.accounts:
            if repo.get_account(session, acc["id"]) is None:
                repo.create_account(
                    session,
                    Account(
                        id=acc["id"],
                        name=acc["name"],
                        industry=acc["industry"],
                        size=acc.get("size"),
                        stage=acc["stage"],
                        deal_value_usd=acc.get("deal_value_usd"),
                    ),
                )
        for contact in data.contacts:
            if repo.get_contact(session, contact["id"]) is None:
                repo.create_contact(
                    session,
                    Contact(
                        id=contact["id"],
                        account_id=contact.get("account_id"),
                        name=contact["name"],
                        aliases=list(contact.get("aliases", [])),
                        role=contact.get("role"),
                    ),
                )
        for m in data.meetings:
            if repo.get_meeting(session, m["id"]) is None:
                repo.create_meeting(
                    session,
                    Meeting(
                        id=m["id"],
                        account_id=m["account_id"],
                        title=m["title"],
                        scheduled_at=_scheduled_at(m["date"]),
                        status="upcoming",
                    ),
                )
            have = {a.contact_id for a in repo.list_attendees_for_meeting(session, m["id"])}
            for contact_id in m["attendees"]:
                if contact_id not in have:
                    repo.add_attendee(session, m["id"], contact_id)


def _ingest_order(data: Seed) -> list[dict[str, Any]]:
    to_ingest = [m for m in data.meetings if m["id"] not in EXCLUDED_FROM_INGEST]
    return sorted(to_ingest, key=lambda m: (m["date"], m["id"]))


def _is_done(session_factory: SessionFactory, meeting_id: str) -> bool:
    with session_factory() as session:
        row = repo.get_meeting(session, meeting_id)
        return row is not None and row.status == "done" and row.ingested_at is not None


def _job_failure_line(session_factory: SessionFactory, job_id: str, code: str) -> str:
    """`job <id> error: <code>: <message>` from the stored job row (message is redacted)."""
    message = ""
    with session_factory() as session:
        job = repo.get_job(session, job_id)
        if job is not None and job.result:
            message = str(job.result.get("error_message", ""))
    return f"job {job_id} error: {code}: {message}"


def _prepare_job(session_factory: SessionFactory, meeting_id: str, transcript: str) -> str:
    with session_factory() as session:
        meetings_repo.save_transcript(session, meeting_id, transcript)
        return ingest_repo.create_job_row(session).id


# ---- core ----


async def seed(
    *,
    memory: MemoryService,
    llm: LLMClient,
    session_factory: SessionFactory,
    ingest_fn: IngestFn = run_ingest,
    seed_data: Seed | None = None,
    transcripts: dict[str, str] | None = None,
    idle_timeout_s: float = WAIT_IDLE_SECONDS,
    log: Log = print,
) -> SeedResult:
    """Seed everything; raise `SeedFailure` at the first failure; return the sanity report."""
    data = seed_data if seed_data is not None else load_seed(SEED_DIR)
    texts = transcripts if transcripts is not None else read_transcripts(data, TRANSCRIPTS_DIR)
    result = SeedResult()

    await memory.ensure_bank()
    _setup(session_factory, data)

    order = _ingest_order(data)
    total = len(order)
    for index, meeting in enumerate(order, start=1):
        meeting_id = meeting["id"]
        tag = f"[{index:02d}/{total:02d}]"
        if _is_done(session_factory, meeting_id):
            log(f"{tag} {meeting_id} skip (already ingested)")
            result.skipped.append(meeting_id)
            continue
        if meeting_id not in texts:
            log(f"{tag} {meeting_id} FAILED missing_transcript")
            raise SeedFailure(meeting_id, "missing_transcript")

        log(f"{tag} {meeting['date']} {meeting_id} start {_clock()}")
        started = time.monotonic()
        try:
            job_id = _prepare_job(session_factory, meeting_id, texts[meeting_id])
            summary = await ingest_fn(
                job_id, meeting_id, llm=llm, memory=memory, session_factory=session_factory
            )
            idle = await memory.wait_until_idle(timeout_s=idle_timeout_s)
        except Exception as exc:  # noqa: BLE001 - any failure stops the run, code reported
            code = exc.code if isinstance(exc, AppError) else "internal_error"
            log(f"{tag} {meeting_id} FAILED {code} after {time.monotonic() - started:.1f}s")
            if job_id is not None:
                log(_job_failure_line(session_factory, job_id, code))
            raise SeedFailure(meeting_id, code, type(exc).__name__) from exc
        elapsed = time.monotonic() - started
        if not idle:
            log(f"{tag} {meeting_id} FAILED memory_not_idle after {elapsed:.1f}s")
            raise SeedFailure(meeting_id, "memory_not_idle")
        log(
            f"{tag} {meeting_id} done in {elapsed:.1f}s (new commitments "
            f"{summary.new_commitments}, closed {summary.closed_commitments}, "
            f"facts {len(summary.facts)})"
        )
        result.ingested.append(meeting_id)

    await _finish_memory(memory, data, idle_timeout_s, log)
    _sanity_report(session_factory, data, result, log)
    return result


async def _finish_memory(memory: MemoryService, data: Seed, idle_s: float, log: Log) -> None:
    if not await memory.wait_until_idle(timeout_s=idle_s):
        log("[final] FAILED memory_not_idle before mental models")
        raise SeedFailure("(all)", "memory_not_idle", "before mental models")
    await memory.ensure_mental_models([(a["id"], a["name"]) for a in data.accounts])
    if not await memory.wait_until_idle(timeout_s=idle_s):
        log("[final] FAILED memory_not_idle after mental models")
        raise SeedFailure("(all)", "memory_not_idle", "after mental models")
    log(f"[final] mental models ready {_clock()}")


# ---- sanity report ----


def _sanity_report(
    session_factory: SessionFactory, data: Seed, result: SeedResult, log: Log
) -> None:
    log("--- summary ---")
    with session_factory() as session:
        by_account = {
            a["id"]: repo.list_commitments_for_account(session, a["id"]) for a in data.accounts
        }
    for account in data.accounts:
        rows = by_account[account["id"]]
        open_rows = [c for c in rows if c.status == CommitmentStatus.open]
        log(f"{account['name']}: {len(open_rows)} open, {len(rows) - len(open_rows)} done")
        for c in sorted(rows, key=lambda c: (c.meeting_id, c.text)):
            due = c.due_date.isoformat() if c.due_date else "no date"
            log(f"  [{c.status.value}] {c.meeting_id} {c.owner.value}: {c.text} (due {due})")

    now = today()
    deck = [
        c
        for c in by_account.get(DECK_ACCOUNT_ID, [])
        if c.meeting_id == DECK_MEETING_ID and DECK_KEYWORD.search(c.text)
    ]
    result.deck_open_overdue = any(
        c.status == CommitmentStatus.open and c.due_date == DECK_DUE and c.due_date < now
        for c in deck
    )
    verdict = "PASS" if result.deck_open_overdue else "FAIL"
    log(f"M4 pricing deck open, due {DECK_DUE}, overdue at {now}: {verdict}")
    if not result.deck_open_overdue:
        result.problems.append(
            f"M4 pricing deck is not an open commitment due {DECK_DUE} that is overdue at {now}"
        )

    for label, account_id, pattern in CHAIN:
        matches = [c for c in by_account.get(account_id, []) if pattern.search(c.text)]
        if any(c.status == CommitmentStatus.done for c in matches):
            result.chain_done.append(label)
            log(f"chain {label}: done")
        else:
            reason = "found but still open" if matches else "no matching commitment"
            log(f"chain {label}: NOT DONE ({reason})")
            result.problems.append(f"promise chain: {label} is not done ({reason})")


# ---- command line ----


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed the demo through the real ingest path.")
    parser.add_argument("--log-file", type=Path, default=None, help="default: ./seed.log")
    parser.add_argument("--idle-timeout", type=float, default=WAIT_IDLE_SECONDS)
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace, log: ProgressLog) -> int:
    from sqlmodel import Session

    from app.db import session as db_session
    from app.memory.memory_service import BANK_ID, HindsightMemoryService
    from app.services.ingest import default_ingest_llm

    db_session.create_db_and_tables()
    memory = HindsightMemoryService()
    try:
        result = await seed(
            memory=memory,
            llm=default_ingest_llm(),
            session_factory=lambda: Session(db_session.engine),
            idle_timeout_s=args.idle_timeout,
            log=log,
        )
    except SeedFailure as failure:
        log(f"STOPPED at {failure.meeting_id}: {failure.code}. Re-run to continue from here.")
        return 1
    finally:
        await memory.aclose()
    if not result.ok:
        log("SANITY CHECK FAILED: " + "; ".join(result.problems))
        return 2
    log(f"seed complete, bank {BANK_ID}")
    return 0


def describe_target(log: Log) -> None:
    """Print the resolved absolute DB path and bank id (first thing every run shows)."""
    from app.config import settings
    from app.memory.memory_service import BANK_ID

    log(f"database: {resolve_db_path(settings.database_url)}")
    log(f"bank:     {BANK_ID}")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    log_path = args.log_file if args.log_file is not None else Path.cwd() / DEFAULT_LOG_NAME
    log = ProgressLog(log_path.resolve())
    describe_target(log)
    log(f"log file: {log.path}")
    try:
        return asyncio.run(_run(args, log))
    except Exception as exc:  # noqa: BLE001 - config or setup errors: message only, no traceback
        log(f"FAILED before ingest: {getattr(exc, 'code', type(exc).__name__)}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
