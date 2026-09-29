"""Reset the demo (ticket T11): wipe the SQLite file and the Hindsight bank, then reseed.

Usage (cwd must be backend/):
    cd backend && uv run python ../data/scripts/reset_demo.py --dry-run
    cd backend && uv run python ../data/scripts/reset_demo.py \
        --confirm-bank ae-priya --confirm-db /abs/path/to/backend/app.db

Safety rules (all enforced in code, all covered by tests):
- it prints the resolved ABSOLUTE database path and the bank id first;
- without BOTH `--confirm-bank` and `--confirm-db` matching those values exactly, it refuses and
  touches nothing; `--dry-run` only prints the plan and never calls Hindsight or the DB;
- the bank id must pass `require_deletable_bank_id` (`ae-<name>` only; never `ami-test`);
- it deletes only the one SQLite file (a regular file, not a symlink, named *.db or *.sqlite)
  and its `-wal` / `-shm` siblings; never anything else in that directory;
- it never touches docker, volumes or any other bank.

Stop a running API first: a running uvicorn keeps the old database file open.
Order: delete the bank (the step that can fail on the network) then the file, recreate tables,
ensure the bank, run the seed with the same progress log (`seed.py`).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent.parent / "backend"
for _p in (_HERE, _BACKEND):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from seed import (  # noqa: E402
    DEFAULT_LOG_NAME,
    WAIT_IDLE_SECONDS,
    ProgressLog,
    SeedFailure,
    resolve_db_path,
    seed,
)

from app.core.errors import ValidationError  # noqa: E402
from app.memory.memory_service import MemoryService, require_deletable_bank_id  # noqa: E402

DB_SUFFIXES = (".db", ".sqlite")

Out = Callable[[str], None]


@dataclass(frozen=True)
class ResetPlan:
    db_path: Path  # absolute
    bank_id: str

    @property
    def sibling_paths(self) -> list[Path]:
        return [
            self.db_path,
            self.db_path.with_name(self.db_path.name + "-wal"),
            self.db_path.with_name(self.db_path.name + "-shm"),
        ]


def _problems(plan: ResetPlan) -> list[str]:
    """Reasons this plan may not run (bank id, file type). Empty means it is safe to run."""
    found: list[str] = []
    try:
        require_deletable_bank_id(plan.bank_id)
    except ValidationError as exc:
        found.append(exc.message)
    path = plan.db_path
    if not path.is_absolute():
        found.append(f"Database path {str(path)!r} is not absolute.")
    if path.suffix not in DB_SUFFIXES:
        found.append(f"Refusing {path.name!r}: file name must end in .db or .sqlite.")
    if path.is_symlink():
        found.append(f"Refusing {str(path)!r}: it is a symlink.")
    elif path.exists() and not path.is_file():
        found.append(f"Refusing {str(path)!r}: it is not a regular file.")
    return found


def _confirm_hint(plan: ResetPlan) -> str:
    return f"--confirm-bank {plan.bank_id} --confirm-db {plan.db_path}"


async def perform_reset(
    plan: ResetPlan,
    *,
    memory: MemoryService | None,
    confirm_bank: str | None,
    confirm_db: str | None,
    dry_run: bool,
    recreate_tables: Callable[[], None],
    run_seed: Callable[[], Awaitable[int]],
    out: Out = print,
) -> int:
    """Returns the process exit code. Raises only if a memory or DB step itself fails."""
    out(f"database: {plan.db_path}")
    out(f"bank:     {plan.bank_id}")
    problems = _problems(plan)

    if dry_run:
        out("DRY RUN: nothing will be touched and Hindsight is not called.")
        for problem in problems:
            out(f"would refuse: {problem}")
        if not problems:
            files = [str(p) for p in plan.sibling_paths if p.exists()]
            out(f"would delete files: {', '.join(files) if files else '(none exist)'}")
            out(f"would delete bank {plan.bank_id!r}, recreate tables, then run the seed")
            out(f"to run for real: make reset-demo RESET_ARGS='{_confirm_hint(plan)}'")
        return 1 if problems else 0

    if confirm_bank != plan.bank_id or confirm_db != str(plan.db_path):
        out("REFUSED: confirmations missing or not an exact match. Nothing was touched.")
        out(f"To confirm, run with: {_confirm_hint(plan)}")
        return 2
    if problems:
        for problem in problems:
            out(f"REFUSED: {problem}")
        return 2

    if memory is None:
        raise AssertionError("a confirmed reset needs a memory service")
    out("WARNING: stop any running API first (uvicorn holds the old database file open).")
    await memory.delete_bank(plan.bank_id)
    out(f"deleted bank {plan.bank_id!r}")
    for path in plan.sibling_paths:
        if path.is_file() and not path.is_symlink():
            path.unlink()
            out(f"deleted {path}")
    recreate_tables()
    await memory.ensure_bank()
    out("tables recreated, bank ensured; seeding")
    return await run_seed()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Wipe the demo DB and bank, then reseed.")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, touch nothing")
    parser.add_argument("--confirm-bank", default=None)
    parser.add_argument("--confirm-db", default=None)
    parser.add_argument("--log-file", type=Path, default=None)
    parser.add_argument("--idle-timeout", type=float, default=WAIT_IDLE_SECONDS)
    return parser.parse_args(argv)


async def _real_reset(plan: ResetPlan, args: argparse.Namespace, log: ProgressLog) -> int:
    from sqlmodel import Session

    from app.db import session as db_session
    from app.memory.memory_service import HindsightMemoryService
    from app.services.ingest import default_ingest_llm

    db_session.engine.dispose()  # release any pooled handle on the old file
    memory = HindsightMemoryService()

    async def run_seed() -> int:
        try:
            result = await seed(
                memory=memory,
                llm=default_ingest_llm(),
                session_factory=lambda: Session(db_session.engine),
                idle_timeout_s=args.idle_timeout,
                log=log,
            )
        except SeedFailure as failure:
            log(f"STOPPED at {failure.meeting_id}: {failure.code}. Run seed.py to continue.")
            return 1
        if not result.ok:
            log("SANITY CHECK FAILED: " + "; ".join(result.problems))
            return 2
        log("reset and seed complete")
        return 0

    try:
        return await perform_reset(
            plan,
            memory=memory,
            confirm_bank=args.confirm_bank,
            confirm_db=args.confirm_db,
            dry_run=False,
            recreate_tables=db_session.create_db_and_tables,
            run_seed=run_seed,
            out=log,
        )
    finally:
        await memory.aclose()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    from app.config import settings
    from app.memory.memory_service import BANK_ID

    plan = ResetPlan(db_path=resolve_db_path(settings.database_url), bank_id=BANK_ID)
    confirmed = args.confirm_bank == plan.bank_id and args.confirm_db == str(plan.db_path)
    if args.dry_run or not confirmed:
        # No memory service is even constructed: nothing here can reach Hindsight.
        return asyncio.run(_offline(plan, dry_run=args.dry_run))
    log_path = args.log_file if args.log_file is not None else Path.cwd() / DEFAULT_LOG_NAME
    log = ProgressLog(log_path.resolve())
    return asyncio.run(_real_reset(plan, args, log))


async def _offline(plan: ResetPlan, *, dry_run: bool) -> int:
    """Dry run or refusal: no memory service, no engine use, no log file."""
    return await perform_reset(
        plan,
        memory=None,
        confirm_bank=None,
        confirm_db=None,
        dry_run=dry_run,
        recreate_tables=_forbidden,
        run_seed=_forbidden_seed,
    )


def _forbidden() -> None:
    raise AssertionError("must not run on this path")


async def _forbidden_seed() -> int:
    raise AssertionError("must not run on this path")


if __name__ == "__main__":
    sys.exit(main())
