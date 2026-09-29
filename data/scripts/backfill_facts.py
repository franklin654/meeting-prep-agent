"""One-time resumable P1-only extracted-fact backfill.

Run from backend/: `uv run python ../data/scripts/backfill_facts.py --dry-run`.
This script writes only the extracted_facts table and never calls Hindsight.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlmodel import Session  # noqa: E402

from app.db.session import engine  # noqa: E402
from app.llm.client import get_llm_client  # noqa: E402
from app.services.facts_backfill import BackfillResult, backfill_facts  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill extracted facts using P1 only.")
    parser.add_argument(
        "--dry-run", action="store_true", help="report eligible meetings without LLM calls"
    )
    parser.add_argument("--limit", type=int, default=None, help="maximum meetings to process")
    return parser


def _report(result: BackfillResult) -> None:
    print(f"eligible={result.eligible} processed={len(result.processed)} calls={result.calls}")
    counts = ", ".join(f"{kind}:{count}" for kind, count in sorted(result.facts_by_kind.items()))
    print("facts_by_kind=" + counts)
    for meeting_id in result.processed:
        meeting_counts = result.facts_by_meeting.get(meeting_id, {})
        kinds = ", ".join(
            f"{kind}:{count}" for kind, count in sorted(meeting_counts.items())
        ) or "none"
        print(f"meeting={meeting_id} facts_by_kind={kinds} total={sum(meeting_counts.values())}")
    if result.processed:
        print(
            f"meetings_with_at_least_2_facts={result.meetings_with_two_facts}/{len(result.processed)}"
        )


async def _run(*, dry_run: bool, limit: int | None) -> BackfillResult:
    def factory() -> Session:
        return Session(engine)

    llm = None if dry_run else get_llm_client(timeout_seconds=120)
    return await backfill_facts(factory, llm, dry_run=dry_run, limit=limit)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.limit is not None and args.limit < 1:
        _parser().error("--limit must be at least 1")
    result = asyncio.run(_run(dry_run=args.dry_run, limit=args.limit))
    _report(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
