"""Transcript generator (ticket T10, prompt G1).

Turns data/seed/beats.json into transcripts through the app's LLM client only
(`app.llm.client.get_llm_client().complete_text`), so it follows LLM_PROVIDER/LLM_MODEL
from the root .env like the app does. No provider SDK is imported here and no key is read
or logged here.

Rules enforced (docs/synthetic-data-spec.md "Generation rules"; AGENTS.md hard rule 12):
- accounts run as parallel lanes (at most 4 requests in flight, one per account); within an
  account meetings are generated strictly in date order, one request at a time;
- a 429 / RateLimitedError is backed off (exponential, bounded) and retried, never fatal;
- any other typed LLM error (timeout, invalid output) or validation failure is retried up to
  4 attempts per transcript; the run then continues and lists the failures;
- temperature 0.8 (prompt-specs.md: G1 at 0.8); no length instruction beyond "natural length";
- a transcript failing validation is never written or patched; only non-length reasons are
  fed back into the retry prompt;
- the live-demo transcript (m6) is generated only with --include-m6, in a single attempt, as
  a DRAFT for hand-editing, and this script REFUSES to write over it once it exists.

Usage:
    cd backend && uv run python ../data/scripts/generate.py            # the 15 generated
    cd backend && uv run python ../data/scripts/generate.py --only m6_finedge --include-m6
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import statistics
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent.parent / "backend"
for _p in (_HERE, _BACKEND):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from validate import (  # noqa: E402
    DEFAULT_DURATION_MINUTES,
    DEFAULT_WORDS,
    LIVE_MEETING_ID,
    LIVE_WORDS,
    SEED_DIR,
    Seed,
    check_transcript,
    load_seed,
    spoken_words,
    transcript_filename,
)

from app.core.errors import AppError, RateLimitedError  # noqa: E402
from app.llm.client import LLMClient  # noqa: E402

PROMPT_PATH = _BACKEND / "app" / "llm" / "prompts" / "generate_transcript.md"
STYLE_REFS_DIR = SEED_DIR / "style_refs"
TEMPERATURE = 0.8  # prompt-specs.md: G1 at 0.8
DEFAULT_MINUTES = 30
LIVE_MINUTES = 10
DEFAULT_PAUSE_SECONDS = 0.0
DEFAULT_MAX_ATTEMPTS = 4  # 1 try + at most 3 regenerations
CALL_TIMEOUT_SECONDS = 300.0  # per-call ceiling passed to get_llm_client
MAX_PARALLEL_LANES = 4
DEFAULT_REJECTED_DIR = Path("/tmp/t10_rejected")  # raw rejected attempts; never in the repo
DEFAULT_RATE_LIMIT_BACKOFF_SECONDS = 20.0
DEFAULT_MAX_RATE_LIMIT_RETRIES = 5
NO_STYLE_REFS = "(none provided; use ordinary, casual business speech between colleagues)"

logger = logging.getLogger("data.generate")


class RefuseOverwriteError(Exception):
    """Raised instead of overwriting the hand-edited live-demo transcript."""


@dataclass
class CallTiming:
    meeting_id: str
    attempt: int
    seconds: float
    words: int
    error: str | None = None


@dataclass
class GenerationResult:
    timings: list[CallTiming] = field(default_factory=list)
    written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    draft_problems: list[str] = field(default_factory=list)
    failure_details: dict[str, list[str]] = field(default_factory=dict)
    attempt_problems: dict[str, list[list[str]]] = field(default_factory=dict)
    rate_limit_events: list[str] = field(default_factory=list)
    total_seconds: float = 0.0


# --------------------------------------------------------------------------- prompt


def load_template() -> str:
    """G1 prompt body with the leading `<!-- ID | model | temperature -->` header removed."""
    raw = PROMPT_PATH.read_text(encoding="utf-8")
    return re.sub(r"\A\s*<!--.*?-->\s*", "", raw, count=1, flags=re.DOTALL)


def _company(seed: Seed, contact: dict[str, object]) -> str:
    account_id = contact["account_id"]
    if account_id is None:
        return str(seed.company["vendor"]["name"])
    return str(next(a for a in seed.accounts if a["id"] == account_id)["name"])


def _cast(seed: Seed, meeting: dict[str, object]) -> str:
    lines = []
    attendees = meeting["attendees"]
    assert isinstance(attendees, list)
    for cid in attendees:
        c = seed.contact(cid)
        line = f"{c['name']} ({c['role']}, {_company(seed, c)}): {c['voice_and_traits']}"
        if c["aliases"]:
            aliases = ", ".join(f'"{a}"' for a in c["aliases"])
            line += f" Priya may occasionally call him {aliases}."
        lines.append(line)
    return "\n".join(lines)


def _previous_summaries(seed: Seed, meeting: dict[str, object]) -> str:
    earlier = sorted(
        (
            m
            for m in seed.meetings
            if m["account_id"] == meeting["account_id"]
            and m["date"] < meeting["date"]
            and m["id"] in seed.beats
        ),
        key=lambda m: m["date"],
    )
    if not earlier:
        return "None; this is the first meeting with this account."
    return "\n".join(
        f"- {m['date']} {m['title']}: "
        + "; ".join(f["text"] for f in seed.beats[m["id"]]["required_facts"])
        for m in earlier
    )


def _style_refs() -> str:
    files = sorted(STYLE_REFS_DIR.glob("*.txt")) if STYLE_REFS_DIR.is_dir() else []
    if not files:
        return NO_STYLE_REFS
    return "\n\n".join(f.read_text(encoding="utf-8").strip() for f in files[:2])


def render_prompt(
    seed: Seed,
    meeting: dict[str, object],
    *,
    minutes: int,
) -> str:
    entry = seed.beats[str(meeting["id"])]
    facts = "\n".join(
        f"- {seed.contact(f['speaker'])['name']}: {f['text']}" for f in entry["required_facts"]
    )
    forbidden = ", ".join(f'"{t}"' for t in entry["forbidden"]) or "nothing in particular"
    return load_template().format(
        date=meeting["date"],
        title=meeting["title"],
        minutes=minutes,
        cast=_cast(seed, meeting),
        previous_summaries=_previous_summaries(seed, meeting),
        style_refs=_style_refs(),
        required_facts=facts,
        forbidden=forbidden,
    )


# --------------------------------------------------------------------------- writing


def write_transcript(path: Path, text: str, *, overwrite: bool) -> None:
    """Write a transcript. The live-demo file is only ever created, never overwritten."""
    protected = path.name == transcript_filename({"id": LIVE_MEETING_ID, "title": ""})
    if protected or not overwrite:
        try:
            with path.open("x", encoding="utf-8") as fh:
                fh.write(text)
        except FileExistsError as exc:
            raise RefuseOverwriteError(
                f"{path.name} already exists; refusing to overwrite it."
            ) from exc
        return
    path.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------- generation


def _is_length_problem(problem: str) -> bool:
    return problem.startswith("word count:")


async def _call_with_backoff(
    client: LLMClient,
    meeting_id: str,
    attempt: int,
    prompt: str,
    result: GenerationResult,
    *,
    sleep: Callable[[float], Awaitable[None]],
    clock: Callable[[], float],
    backoff_seconds: float,
    max_retries: int,
) -> tuple[str, float]:
    """One request; a 429 is backed off (exponential, bounded) and retried, then re-raised."""
    retries = 0
    while True:
        started = clock()
        try:
            text = await client.complete_text(prompt, temperature=TEMPERATURE)
        except RateLimitedError:
            result.timings.append(
                CallTiming(meeting_id, attempt, clock() - started, 0, "RateLimitedError")
            )
            if retries >= max_retries:
                raise
            delay = backoff_seconds * (2**retries)
            retries += 1
            event = (
                f"llm.rate_limited meeting={meeting_id} attempt={attempt} "
                f"retry={retries}/{max_retries} backoff={delay:.0f}s"
            )
            result.rate_limit_events.append(event)
            logger.warning(event)
            await sleep(delay)
            continue
        return text, clock() - started


def _select(seed: Seed, only: set[str] | None, include_m6: bool) -> list[dict[str, object]]:
    chosen = [
        m
        for m in seed.meetings
        if m["id"] in seed.beats
        and (only is None or m["id"] in only)
        and (include_m6 or m["id"] != LIVE_MEETING_ID)
    ]
    return sorted(chosen, key=lambda m: (str(m["date"]), str(m["id"])))


async def generate_transcripts(
    client: LLMClient,
    seed: Seed,
    out_dir: Path,
    *,
    pause_seconds: float = DEFAULT_PAUSE_SECONDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    only: set[str] | None = None,
    include_m6: bool = False,
    force: bool = False,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    rate_limit_backoff_seconds: float = DEFAULT_RATE_LIMIT_BACKOFF_SECONDS,
    max_rate_limit_retries: int = DEFAULT_MAX_RATE_LIMIT_RETRIES,
    max_parallel: int = MAX_PARALLEL_LANES,
    rejected_dir: Path | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> GenerationResult:
    """Generate the selected transcripts. See the module docstring for the rules."""
    result = GenerationResult()
    meetings = _select(seed, only, include_m6)
    out_dir.mkdir(parents=True, exist_ok=True)

    live_path = out_dir / transcript_filename({"id": LIVE_MEETING_ID, "title": ""})
    if any(m["id"] == LIVE_MEETING_ID for m in meetings) and live_path.exists():
        raise RefuseOverwriteError(f"{live_path.name} already exists; refusing to overwrite it.")

    async def process(meeting: dict[str, object], first: bool) -> None:
        mid = str(meeting["id"])
        is_live = mid == LIVE_MEETING_ID
        path = out_dir / transcript_filename(meeting)
        word_range = LIVE_WORDS if is_live else DEFAULT_WORDS
        duration = None if is_live else DEFAULT_DURATION_MINUTES
        base_prompt = render_prompt(
            seed, meeting, minutes=LIVE_MINUTES if is_live else DEFAULT_MINUTES
        )
        prompt = base_prompt
        history = result.attempt_problems.setdefault(mid, [])
        for attempt in range(1, (1 if is_live else max_attempts) + 1):
            if (attempt > 1 or not first) and pause_seconds > 0:
                await sleep(pause_seconds)
            started = clock()
            try:
                text, seconds = await _call_with_backoff(
                    client,
                    mid,
                    attempt,
                    prompt,
                    result,
                    sleep=sleep,
                    clock=clock,
                    backoff_seconds=rate_limit_backoff_seconds,
                    max_retries=max_rate_limit_retries,
                )
            except AppError as exc:
                if not isinstance(exc, RateLimitedError):
                    result.timings.append(
                        CallTiming(mid, attempt, clock() - started, 0, type(exc).__name__)
                    )
                logger.warning(
                    "gen.error meeting=%s attempt=%d error=%s", mid, attempt, type(exc).__name__
                )
                history.append([f"{type(exc).__name__}: {exc}"])
                prompt = base_prompt
                continue
            text = text.strip() + "\n"
            problems = check_transcript(
                seed, seed.meeting(mid), text, words=word_range, duration=duration
            )
            words = spoken_words(text)
            history.append(problems)
            result.timings.append(CallTiming(mid, attempt, seconds, words))
            logger.info(
                "gen.call meeting=%s attempt=%d seconds=%.1f words=%d problems=%d",
                mid,
                attempt,
                seconds,
                words,
                len(problems),
            )
            if is_live:
                write_transcript(path, text, overwrite=False)
                result.written.append(mid)
                result.draft_problems = problems
                return
            if not problems:
                write_transcript(path, text, overwrite=force)
                result.written.append(mid)
                return
            if rejected_dir is not None:
                rejected_dir.mkdir(parents=True, exist_ok=True)
                (rejected_dir / f"{mid}_attempt{attempt}.txt").write_text(text, encoding="utf-8")
            feedback = [p for p in problems if not _is_length_problem(p)]
            prompt = base_prompt
            if feedback:
                prompt += (
                    "\n\nPrevious attempt was rejected for these reasons; fix them:\n"
                    + "\n".join(f"- {p}" for p in feedback[:8])
                )
        result.failed.append(mid)
        result.failure_details[mid] = history[-1] if history else []

    lanes: dict[str, list[dict[str, object]]] = {}
    for meeting in meetings:
        mid = str(meeting["id"])
        if (
            (out_dir / transcript_filename(meeting)).exists()
            and mid != LIVE_MEETING_ID
            and not force
        ):
            result.skipped.append(mid)
            continue
        lanes.setdefault(str(meeting["account_id"]), []).append(meeting)

    semaphore = asyncio.Semaphore(max_parallel)

    async def lane(items: list[dict[str, object]]) -> None:
        async with semaphore:
            for index, meeting in enumerate(items):
                await process(meeting, first=index == 0)

    started_all = clock()
    await asyncio.gather(*(lane(items) for items in lanes.values()))
    result.total_seconds = clock() - started_all
    return result


# --------------------------------------------------------------------------- CLI


def timing_summary(result: GenerationResult) -> str:
    if not result.timings:
        return "no generation calls were made"
    secs = [t.seconds for t in result.timings]
    lines = [
        f"calls={len(secs)} min={min(secs):.1f}s median={statistics.median(secs):.1f}s "
        f"max={max(secs):.1f}s sum={sum(secs):.1f}s wall_clock={result.total_seconds:.1f}s"
    ]
    for t in result.timings:
        note = f" error={t.error}" if t.error else ""
        lines.append(f"  {t.meeting_id} attempt={t.attempt} {t.seconds:.1f}s words={t.words}{note}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate seed transcripts (G1).")
    parser.add_argument("--seed-dir", type=Path, default=SEED_DIR)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--only", nargs="*", default=None, help="meeting ids to generate")
    parser.add_argument("--include-m6", action="store_true", help="also draft the live-demo file")
    parser.add_argument("--force", action="store_true", help="regenerate existing (never m6)")
    parser.add_argument("--pause", type=float, default=DEFAULT_PAUSE_SECONDS)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(name)s %(message)s"
    )
    for noisy in ("httpx", "httpx2", "httpcore", "openai", "anthropic", "groq"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    from app.llm.client import get_llm_client

    seed = load_seed(args.seed_dir)
    out_dir = args.out_dir or (args.seed_dir / "transcripts")
    client = get_llm_client(timeout_seconds=CALL_TIMEOUT_SECONDS)
    try:
        result = asyncio.run(
            generate_transcripts(
                client,
                seed,
                out_dir,
                pause_seconds=args.pause,
                only=set(args.only) if args.only else None,
                include_m6=args.include_m6,
                force=args.force,
                max_attempts=args.max_attempts,
                rejected_dir=DEFAULT_REJECTED_DIR,
            )
        )
    except RefuseOverwriteError as exc:
        print(f"REFUSED: {exc}")
        return 3

    print(f"written: {result.written}")
    print(f"skipped (already exist): {result.skipped}")
    print(f"failed validation after retries (not written): {result.failed}")
    for mid in result.failed:
        for n, reasons in enumerate(result.attempt_problems.get(mid, []), start=1):
            print(f"  {mid} attempt {n}: {reasons}")
    for event in result.rate_limit_events:
        print(f"rate limit: {event}")
    if result.draft_problems:
        print(f"{LIVE_MEETING_ID} draft findings (not fixed): {result.draft_problems}")
    print(timing_summary(result))
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
