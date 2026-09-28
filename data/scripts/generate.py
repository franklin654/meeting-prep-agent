"""Transcript generator (ticket T10, prompt G1).

Turns data/seed/beats.json into transcripts through the app's LLM client only
(`app.llm.client.get_llm_client().complete_text`), so it follows LLM_PROVIDER/LLM_MODEL
from the root .env like the app does. No provider SDK is imported here and no key is read
or logged here.

Rules enforced (docs/synthetic-data-spec.md "Generation rules"; AGENTS.md hard rule 12):
- one meeting at a time, in date order; strictly one request in flight; a configurable
  pause between calls; 429 backoff is the client's job;
- ANY `llm.rate_limited` log line or typed LLM error stops the run immediately;
- temperature 0.8 (prompt-specs.md: G1 at 0.8);
- a transcript failing validation is regenerated (bounded), never patched, never written;
- the live-demo transcript (m6) is generated only with --include-m6, at most once, as a
  DRAFT for hand-editing, and this script REFUSES to write over it once it exists.

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
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
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
    transcript_filename,
)

from app.core.errors import AppError  # noqa: E402
from app.llm.client import LLMClient  # noqa: E402

PROMPT_PATH = _BACKEND / "app" / "llm" / "prompts" / "generate_transcript.md"
STYLE_REFS_DIR = SEED_DIR / "style_refs"
TEMPERATURE = 0.8  # prompt-specs.md: G1 at 0.8
DEFAULT_MINUTES = 30
LIVE_MINUTES = 10
DEFAULT_PAUSE_SECONDS = 0.0
CALL_TIMEOUT_SECONDS = 180.0  # per-call ceiling; a call exceeding it stops the run
DEFAULT_MAX_ATTEMPTS = 3  # 1 try + at most 2 regenerations
NO_STYLE_REFS = "(none provided; use ordinary, casual business speech between colleagues)"

logger = logging.getLogger("data.generate")


class RefuseOverwriteError(Exception):
    """Raised instead of overwriting the hand-edited live-demo transcript."""


class GenerationAborted(Exception):  # noqa: N818 - reads better than GenerationAbortedError
    """The run was stopped on purpose (rate limit or typed LLM error); carries partial results."""

    def __init__(self, reason: str, result: GenerationResult) -> None:
        super().__init__(reason)
        self.reason = reason
        self.result = result


@dataclass
class CallTiming:
    meeting_id: str
    attempt: int
    seconds: float
    words: int


@dataclass
class GenerationResult:
    timings: list[CallTiming] = field(default_factory=list)
    written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    draft_problems: list[str] = field(default_factory=list)
    failure_details: dict[str, list[str]] = field(default_factory=dict)
    rate_limit_evidence: list[str] = field(default_factory=list)


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
    word_range: tuple[int, int],
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
        min_words=word_range[0],
        max_words=word_range[1],
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


# --------------------------------------------------------------------------- rate-limit watch


class RateLimitWatch(logging.Handler):
    """Cancels the in-flight call the moment the client logs `llm.rate_limited`."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.evidence: list[str] = []
        self.task: asyncio.Future[str] | None = None

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if "llm.rate_limited" not in message:
            return
        self.evidence.append(message)
        if self.task is not None and not self.task.done():
            self.task.cancel()

    @property
    def tripped(self) -> bool:
        return bool(self.evidence)


@contextmanager
def watching_rate_limits() -> Iterator[RateLimitWatch]:
    watch = RateLimitWatch()
    llm_logger = logging.getLogger("app.llm")
    previous_level = llm_logger.level
    if previous_level == logging.NOTSET or previous_level > logging.INFO:
        llm_logger.setLevel(logging.INFO)
    llm_logger.addHandler(watch)
    try:
        yield watch
    finally:
        llm_logger.removeHandler(watch)
        llm_logger.setLevel(previous_level)


# --------------------------------------------------------------------------- generation


def _abort(reason: str, result: GenerationResult, watch: RateLimitWatch) -> GenerationAborted:
    result.rate_limit_evidence = list(watch.evidence)
    return GenerationAborted(reason, result)


async def _one_call(
    client: LLMClient, prompt: str, watch: RateLimitWatch, result: GenerationResult
) -> str:
    task: asyncio.Future[str] = asyncio.ensure_future(
        client.complete_text(prompt, temperature=TEMPERATURE)
    )
    watch.task = task
    try:
        text = await task
    except asyncio.CancelledError:
        if watch.tripped:
            raise _abort(
                f"rate limit hit ({watch.evidence[0]}); run stopped", result, watch
            ) from None
        raise
    except AppError as exc:
        raise _abort(f"{type(exc).__name__}: {exc}", result, watch) from exc
    finally:
        watch.task = None
    if watch.tripped:
        raise _abort(f"rate limit hit ({watch.evidence[0]}); run stopped", result, watch)
    return text


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
    clock: Callable[[], float] = time.monotonic,
) -> GenerationResult:
    """Generate the selected transcripts one request at a time. See module docstring."""
    result = GenerationResult()
    meetings = _select(seed, only, include_m6)
    out_dir.mkdir(parents=True, exist_ok=True)

    live_path = out_dir / transcript_filename({"id": LIVE_MEETING_ID, "title": ""})
    if any(m["id"] == LIVE_MEETING_ID for m in meetings) and live_path.exists():
        raise RefuseOverwriteError(f"{live_path.name} already exists; refusing to overwrite it.")

    first_call = True
    with watching_rate_limits() as watch:
        for meeting in meetings:
            mid = str(meeting["id"])
            is_live = mid == LIVE_MEETING_ID
            path = out_dir / transcript_filename(meeting)
            if path.exists() and not is_live and not force:
                result.skipped.append(mid)
                continue
            word_range = LIVE_WORDS if is_live else DEFAULT_WORDS
            duration = None if is_live else DEFAULT_DURATION_MINUTES
            base_prompt = render_prompt(
                seed,
                meeting,
                word_range=word_range,
                minutes=LIVE_MINUTES if is_live else DEFAULT_MINUTES,
            )
            attempts = 1 if is_live else max_attempts
            prompt = base_prompt
            problems: list[str] = []
            for attempt in range(1, attempts + 1):
                if not first_call and pause_seconds > 0:
                    await sleep(pause_seconds)
                first_call = False
                started = clock()
                try:
                    text = await _one_call(client, prompt, watch, result)
                except GenerationAborted:
                    result.timings.append(CallTiming(mid, attempt, clock() - started, 0))
                    raise
                seconds = clock() - started
                text = text.strip() + "\n"
                problems = check_transcript(
                    seed, seed.meeting(mid), text, words=word_range, duration=duration
                )
                words = sum(len(line.split(": ", 1)[-1].split()) for line in text.splitlines())
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
                    break
                if not problems:
                    write_transcript(path, text, overwrite=force)
                    result.written.append(mid)
                    break
                prompt = (
                    base_prompt
                    + "\n\nPrevious attempt was rejected for these reasons; fix them:\n"
                    + "\n".join(f"- {p}" for p in problems[:8])
                )
            else:
                result.failed.append(mid)
                result.failure_details[mid] = problems
                raise GenerationAborted(
                    f"{mid} failed validation after {max_attempts} attempts; run stopped", result
                )
    return result


# --------------------------------------------------------------------------- CLI


def timing_summary(result: GenerationResult) -> str:
    if not result.timings:
        return "no generation calls were made"
    secs = [t.seconds for t in result.timings]
    lines = [
        f"calls={len(secs)} min={min(secs):.1f}s median={statistics.median(secs):.1f}s "
        f"max={max(secs):.1f}s total={sum(secs):.1f}s"
    ]
    for t in result.timings:
        lines.append(f"  {t.meeting_id} attempt={t.attempt} {t.seconds:.1f}s words={t.words}")
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
            )
        )
    except RefuseOverwriteError as exc:
        print(f"REFUSED: {exc}")
        return 3
    except GenerationAborted as exc:
        print(f"ABORTED: {exc.reason}")
        for line in exc.result.rate_limit_evidence:
            print(f"evidence: {line}")
        for mid, details in exc.result.failure_details.items():
            print(f"  {mid}: {details}")
        print(f"written before abort: {exc.result.written}")
        print(timing_summary(exc.result))
        return 2

    print(f"written: {result.written}")
    print(f"skipped (already exist): {result.skipped}")
    print(f"failed validation after retries (not written): {result.failed}")
    for mid, details in result.failure_details.items():
        print(f"  {mid}: {details}")
    if result.draft_problems:
        print(f"{LIVE_MEETING_ID} draft findings (not fixed): {result.draft_problems}")
    print(timing_summary(result))
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
