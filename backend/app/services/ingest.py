"""Ingest service (docs/technical-design.md "Ingest (after a meeting)"; ticket T12).

`run_ingest(job_id, meeting_id, ...)` is the one function the background task and the
seed script both call. Order (each step matters, see the numbered comments):

0. idempotency: drop this meeting's commitments, reopen those it closed
1. load meeting, attendees, account, transcript
2. P1 extraction (temperature 0)
3. drop items whose `source_quote` is not verbatim in the transcript
4. entity resolution (account contacts first, then our own people)
5. P2 acknowledgement matching, only against open commitments from EARLIER meetings
6. close matched commitments
7. create this transcript's commitments (after P2, so they can never be closed by it)
8. update the account's deal value when a budget was stated
9. retain the transcript in memory
10. mark the meeting done, only after the retain succeeded
11. store the `LearnedSummary` on the job

Failures set the job to `failed` with the typed error code and re-raise, so a caller
such as the seed script can stop; `run_ingest_job` is the background wrapper that
swallows (after recording and logging) so a bad job never kills the worker.
There are no retries here beyond the LLM client's own (one invalid-output retry,
429 backoff). Transcripts are never logged.
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import date

from sqlmodel import Session

from app.core.errors import AppError, NotFoundError
from app.db import ingest_repo, repository
from app.db.models import Commitment, Contact
from app.llm.client import LLMClient, get_llm_client
from app.llm.prompt_loader import render_prompt
from app.memory.memory_service import MemoryService
from app.schemas.ack import AckMatches
from app.schemas.api import LearnedSummary
from app.schemas.enums import Owner
from app.schemas.extraction import (
    Acknowledgement,
    ExtractedCommitment,
    ExtractedFact,
    MeetingExtraction,
    PersonMention,
)

logger = logging.getLogger(__name__)

INGEST_LLM_TIMEOUT_SECONDS = 120
# Client-side limit for `memory.retain_meeting` during ingest (the default is 30 s; a real
# retain took 34.7 s while Hindsight still finished it). Passed on every retain in `_ingest`.
INGEST_RETAIN_TIMEOUT_S = 120.0
ERROR_MESSAGE_MAX_CHARS = 300
# Our own company; the seed data's vendor (data/seed/company.json). Not configurable yet.
OUR_COMPANY = "Tracewise"
MAX_QUOTE_CHARS = 200
MAX_COMMITMENTS_PER_MEETING = 5
NEAR_DUPLICATE_JACCARD = 0.8

# Deterministic backstop for meeting logistics/prep that P1 sometimes still returns. Both lists
# are matched as whole words/phrases on the commitment TEXT after `_normalize_name`
# (lowercase, punctuation to spaces: "one-pager" -> "one pager", "SOC 2" -> "soc 2").
# An item is dropped when its text contains a logistics term or starts with a logistics verb,
# UNLESS it also names a substantive deliverable from the allow list (allow list always wins,
# so the planted deliverables can never be filtered out).
LOGISTICS_TERMS: tuple[str, ...] = (
    "recap",
    "agenda",
    "minutes",
    "attendee",
    "attendees",
    "invite",
    "invitation",
    "calendar",
    "scheduling",
    "questionnaire",
    "checklist",
    "session outline",
    "information needed",
)
LOGISTICS_LEADING_VERBS: tuple[str, ...] = (
    "bring",
    "prepare",
    "identify",
    "ask",
    "confirm",
    "schedule",
    "book",
)
DELIVERABLE_ALLOW_TERMS: tuple[str, ...] = (
    "deck",
    "pricing",
    "proposal",
    "quote",
    "comparison",
    "case study",
    "one pager",
    "report",
    "configs",
    "config",
    "access",
    "credentials",
    "portal",
    "sandbox",
    "pen test",
    "shortlist",
    "soc 2",
    "security package",
    "data flow",
    "migration plan",
    "questionnaire responses",
    "security questionnaire",
    "security reviewer",
    "data residency",
    "quick start guide",
    "executed copy",
    "countersigned version",
    "architecture details",
    "checks they would keep",
    "vendor information",
    "proposed onboarding",
    "incident outline",
    "checks to keep or test",
    "document the checks",
    "expansion from a smaller initial pipeline scope",
)

SessionFactory = Callable[[], AbstractContextManager[Session]]

_GENERIC_FIRST_WORDS = frozenset(
    "the a an their our his her its your my some someone somebody we i you he she they it "
    "them us who".split()
)
_PUNCT_MAP = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        "…": "...",
        " ": " ",
    }
)


_SECRET_PATTERNS = (
    re.compile(r"(?i)bearer\s+\S+"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"\bgsk_[A-Za-z0-9_\-]{6,}"),
    re.compile(r"[A-Za-z0-9+/=_\-]{32,}"),
)


def safe_error_message(exc: BaseException) -> str:
    """Short, secret-free description of `exc` for the job row (never prompt/transcript text).

    Cuts at the first newline, `{` or the word "body" (HTTP bodies can echo the request),
    redacts key-like tokens (sk-..., gsk_..., Bearer ..., long base64-ish strings), then
    truncates to `ERROR_MESSAGE_MAX_CHARS`.
    """
    text = re.split(r"\n|\{|\bbody\b", str(exc), maxsplit=1)[0].strip()
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    text = text.strip() or type(exc).__name__
    return text[:ERROR_MESSAGE_MAX_CHARS]


def default_ingest_llm() -> LLMClient:
    """The app LLM with the long ingest timeout; every P1 and P2 call uses it."""
    return get_llm_client(timeout_seconds=INGEST_LLM_TIMEOUT_SECONDS)


# ---- text helpers ----


def normalize_text(text: str) -> str:
    """Normalisation used for the verbatim-quote check.

    Unicode NFKC, curly quotes/dashes/ellipsis mapped to ASCII, runs of whitespace
    collapsed to one space, casefolded, and edges stripped. Words and their order must
    still match exactly; only formatting and case differences are forgiven.
    """
    mapped = unicodedata.normalize("NFKC", text).translate(_PUNCT_MAP)
    return re.sub(r"\s+", " ", mapped).casefold().strip()


def _normalize_name(name: str) -> str:
    stripped = re.sub(r"[^\w\s]", " ", unicodedata.normalize("NFKC", name).casefold())
    return re.sub(r"\s+", " ", stripped).strip()


def is_verbatim(quote: str, normalized_transcript: str) -> bool:
    normalized_quote = normalize_text(quote)
    return bool(normalized_quote) and normalized_quote in normalized_transcript


def _clip(quote: str) -> str:
    quote = quote.strip()
    return quote if len(quote) <= MAX_QUOTE_CHARS else quote[:MAX_QUOTE_CHARS].rstrip()


# ---- extraction filtering ----


@dataclass
class _Verified:
    commitments: list[ExtractedCommitment]
    acknowledgements: list[Acknowledgement]
    facts: list[ExtractedFact]
    dropped: int


def _verify_quotes(extraction: MeetingExtraction, transcript: str) -> _Verified:
    norm = normalize_text(transcript)
    commitments = [c for c in extraction.commitments if is_verbatim(c.source_quote, norm)]
    acks = [a for a in extraction.acknowledgements if is_verbatim(a.source_quote, norm)]
    facts = [f for f in extraction.facts if is_verbatim(f.source_quote, norm)]
    dropped = (
        (len(extraction.commitments) - len(commitments))
        + (len(extraction.acknowledgements) - len(acks))
        + (len(extraction.facts) - len(facts))
    )
    return _Verified(commitments, acks, facts, dropped)


def _words(text: str) -> frozenset[str]:
    return frozenset(_normalize_name(text).split())


def _is_near_duplicate(a: ExtractedCommitment, b: ExtractedCommitment) -> bool:
    """Same normalized text, word-set Jaccard >= 0.8, or same owner_person with containment."""
    if normalize_text(a.source_quote) == normalize_text(b.source_quote):
        return True  # same sentence, same promise
    text_a, text_b = _normalize_name(a.text), _normalize_name(b.text)
    if not text_a or not text_b:
        return False
    if text_a == text_b:
        return True
    words_a, words_b = _words(a.text), _words(b.text)
    if (
        words_a
        and words_b
        and len(words_a & words_b) / len(words_a | words_b) >= (NEAR_DUPLICATE_JACCARD)
    ):
        return True
    same_person = _normalize_name(a.owner_person) == _normalize_name(b.owner_person)
    return same_person and (text_a in text_b or text_b in text_a)


def _has_term(padded_text: str, terms: Sequence[str]) -> bool:
    return any(f" {term} " in padded_text for term in terms)


def is_logistics(text: str) -> bool:
    """True for meeting logistics/prep wording with no substantive deliverable noun."""
    normalized = _normalize_name(text)
    padded = f" {normalized} "
    if _has_term(padded, DELIVERABLE_ALLOW_TERMS):
        return False
    first = normalized.split(" ", 1)[0] if normalized else ""
    return first in LOGISTICS_LEADING_VERBS or _has_term(padded, LOGISTICS_TERMS)


def filter_logistics(
    commitments: Sequence[ExtractedCommitment],
) -> tuple[list[ExtractedCommitment], int]:
    """Drop logistics/prep items (see `LOGISTICS_TERMS`); returns `(kept, dropped_count)`."""
    kept = [c for c in commitments if not is_logistics(c.text)]
    return kept, len(commitments) - len(kept)


def consolidate_commitments(
    commitments: Sequence[ExtractedCommitment], normalized_transcript: str = ""
) -> tuple[list[ExtractedCommitment], int, int]:
    """Drop logistics items, merge duplicates, then hard-cap at `MAX_COMMITMENTS_PER_MEETING`.

    Logistics items are dropped first so a dated recap can never outrank an undated real
    deliverable. Items citing the same normalized `source_quote` are one promise.

    Returns `(kept, merged_count, capped_count)`. A merged group keeps the longer (more
    specific) text, the quote that appears earliest in the transcript (extraction order if
    positions tie or are unknown) and any due date (the earliest if several). Dated
    commitments are kept first when capping, then extraction order.
    """

    def position(item: ExtractedCommitment) -> int:
        found = normalized_transcript.find(normalize_text(item.source_quote))
        return found if found >= 0 else len(normalized_transcript)

    groups: list[ExtractedCommitment] = []
    merged = 0
    for item in filter_logistics(commitments)[0]:
        for idx, kept in enumerate(groups):
            if _is_near_duplicate(kept, item):
                first, other = (kept, item) if position(kept) <= position(item) else (item, kept)
                dues = [d for d in (kept.due_date, item.due_date) if d is not None]
                groups[idx] = first.model_copy(
                    update={
                        "text": max(kept.text, item.text, key=lambda t: len(t.strip())),
                        "due_date": min(dues) if dues else None,
                        "owner_person": first.owner_person or other.owner_person,
                    }
                )
                merged += 1
                break
        else:
            groups.append(item)
    ordered = sorted(groups, key=lambda c: c.due_date is None)  # stable: dated first
    capped = max(0, len(ordered) - MAX_COMMITMENTS_PER_MEETING)
    return ordered[:MAX_COMMITMENTS_PER_MEETING], merged, capped


# ---- entity resolution ----


@dataclass
class _Resolver:
    """Resolves a name as said to a `Contact`, creating flagged contacts for unknown people.

    Match order: pool 1 is the meeting's account contacts, pool 2 is our own people. Within
    a pool a match is the full name, an alias, or (only when unique in that pool) a single
    name token such as a first name. Comparison uses `_normalize_name`.
    """

    session: Session
    account_id: str
    account_contacts: list[Contact]
    own_contacts: list[Contact]
    created: list[Contact] = field(default_factory=list)

    @classmethod
    def load(cls, session: Session, account_id: str) -> _Resolver:
        contacts = ingest_repo.list_contacts_for_matching(session, account_id)
        return cls(
            session=session,
            account_id=account_id,
            account_contacts=[c for c in contacts if c.account_id == account_id],
            own_contacts=[c for c in contacts if c.account_id is None],
        )

    def find(self, name: str) -> Contact | None:
        wanted = _normalize_name(name)
        if not wanted:
            return None
        for pool in (self.account_contacts, self.own_contacts):
            exact = [
                c
                for c in pool
                if wanted == _normalize_name(c.name)
                or wanted in {_normalize_name(a) for a in c.aliases}
            ]
            if exact:
                return exact[0]
            token_hits = [c for c in pool if wanted in _normalize_name(c.name).split()]
            if len(token_hits) == 1:
                return token_hits[0]
        return None

    def resolve(self, mention: PersonMention | str) -> Contact | None:
        """Existing contact, else a new `needs_review` contact; None for generic references."""
        if isinstance(mention, str):
            mention = PersonMention(name_as_said=mention, role_if_stated=None, organisation=None)
        name = mention.name_as_said.strip()
        found = self.find(name)
        if found is not None:
            return found
        words = _normalize_name(name).split()
        if not words or words[0] in _GENERIC_FIRST_WORDS:
            return None  # "their CFO", "someone": not a nameable person
        ours = bool(
            mention.organisation
            and _normalize_name(mention.organisation) == _normalize_name(OUR_COMPANY)
        )
        contact = Contact(
            id=ingest_repo.new_id("c"),
            account_id=None if ours else self.account_id,
            name=name,
            aliases=[],
            role=mention.role_if_stated,
            needs_review=True,
        )
        contact = repository.create_contact(self.session, contact)
        (self.own_contacts if ours else self.account_contacts).append(contact)
        self.created.append(contact)
        return contact


# ---- P2 ----


def _match_commitment_ids(
    matches: AckMatches, open_commitments: Sequence[Commitment], ack_count: int
) -> list[str]:
    valid = {c.id for c in open_commitments}
    matched: list[str] = []
    dropped = 0
    for match in matches.closed:
        if match.commitment_id in valid and 0 <= match.acknowledgement_index < ack_count:
            if match.commitment_id not in matched:
                matched.append(match.commitment_id)
        else:
            dropped += 1
    if dropped:
        logger.warning("ingest p2 dropped_invalid_matches=%d", dropped)
    return matched


def _format_open_commitment(commitment: Commitment) -> str:
    """`id: text | original words: "quote"`, so P2 can match an acknowledgement that uses
    different words than the commitment's text (docs: quote truncated to 200 chars)."""
    quote = " ".join(commitment.source_quote.split())[:MAX_QUOTE_CHARS]
    return f'{commitment.id}: {commitment.text} | original words: "{quote}"'


def _format_ack(index: int, ack: Acknowledgement) -> str:
    return f'{index}: {ack.description} — "{ack.source_quote}"'


# ---- summary ----


def _format_usd(amount: int) -> str:
    return f"${amount:,}"


# ---- main entry points ----


async def run_ingest(
    job_id: str,
    meeting_id: str,
    *,
    llm: LLMClient,
    memory: MemoryService,
    session_factory: SessionFactory,
) -> LearnedSummary:
    """Ingest one meeting's transcript. Records the outcome on the job and re-raises errors."""
    started = time.monotonic()
    try:
        with session_factory() as session:
            summary = await _ingest(session, meeting_id, llm=llm, memory=memory)
            ingest_repo.finish_job(session, job_id, result=summary.model_dump(mode="json"))
    except Exception as exc:
        code = exc.code if isinstance(exc, AppError) else "internal_error"
        message = safe_error_message(exc)
        logger.error(
            "ingest failed job=%s meeting=%s code=%s error_type=%s message_len=%d",
            job_id,
            meeting_id,
            code,
            type(exc).__name__,
            len(message),
        )
        with session_factory() as session:
            ingest_repo.finish_job(
                session,
                job_id,
                error=code,
                result={"error_code": code, "error_message": message},
            )
        raise
    logger.info(
        "ingest done job=%s meeting=%s duration_ms=%d",
        job_id,
        meeting_id,
        int((time.monotonic() - started) * 1000),
    )
    return summary


async def run_ingest_job(
    job_id: str,
    meeting_id: str,
    *,
    llm: LLMClient,
    memory: MemoryService,
    session_factory: SessionFactory,
) -> None:
    """Background-task wrapper: `run_ingest` already recorded any failure on the job."""
    try:
        await run_ingest(
            job_id, meeting_id, llm=llm, memory=memory, session_factory=session_factory
        )
    except Exception:  # noqa: BLE001 - recorded on the job and logged by run_ingest
        return


async def _ingest(
    session: Session, meeting_id: str, *, llm: LLMClient, memory: MemoryService
) -> LearnedSummary:
    # 0. Idempotency: a rerun recomputes the ledger for this meeting from scratch.
    reopened = ingest_repo.reopen_commitments_closed_by(session, meeting_id)
    removed = ingest_repo.delete_commitments_for_meeting(session, meeting_id)
    if reopened or removed:
        logger.info("ingest rerun meeting=%s reopened=%d removed=%d", meeting_id, reopened, removed)

    # 1. Load.
    meeting, attendees = ingest_repo.get_meeting_with_attendees(session, meeting_id)
    if not meeting.transcript or not meeting.transcript.strip():
        raise NotFoundError(f"Meeting {meeting_id!r} has no transcript to ingest.")
    account = repository.get_account(session, meeting.account_id)
    if account is None:
        raise NotFoundError(f"Account {meeting.account_id!r} not found.")
    account_id, account_name = account.id, account.name
    transcript, title = meeting.transcript, meeting.title
    scheduled_at = meeting.scheduled_at
    meeting_date = scheduled_at.date()
    attendee_ids = [a.id for a in attendees]

    resolver = _Resolver.load(session, account_id)

    # 2. P1.
    prompt = render_prompt(
        "extract_meeting",
        our_company=OUR_COMPANY,
        our_people=", ".join(c.name for c in resolver.own_contacts) or "(none)",
        meeting_title=title,
        meeting_date=meeting_date.isoformat(),
        account_name=account_name,
        known_contacts="; ".join(_describe_contact(c) for c in resolver.account_contacts)
        or "(none)",
        transcript=transcript,
    )
    t0 = time.monotonic()
    extraction = await llm.complete_json(prompt, MeetingExtraction, temperature=0.0)
    logger.info(
        "ingest p1 meeting=%s duration_ms=%d", meeting_id, int((time.monotonic() - t0) * 1000)
    )

    # 3. Verbatim-quote filter.
    verified = _verify_quotes(extraction, transcript)
    if verified.dropped:
        logger.warning(
            "ingest dropped_unverbatim_items=%d meeting=%s", verified.dropped, meeting_id
        )

    consolidated, merged, capped = consolidate_commitments(
        verified.commitments, normalize_text(transcript)
    )
    logistics_dropped = filter_logistics(verified.commitments)[1]
    verified.commitments = consolidated
    if merged or capped or logistics_dropped:
        logger.info(
            "ingest commitments logistics_dropped=%d merged=%d capped=%d kept=%d meeting=%s",
            logistics_dropped,
            merged,
            capped,
            len(consolidated),
            meeting_id,
        )

    # 4. Entity resolution.
    for person in extraction.people:
        resolver.resolve(person)

    # 5. P2, against open commitments from earlier meetings only.
    closed_ids: list[str] = []
    earlier_open = ingest_repo.list_open_commitments(
        session, account_id, before=scheduled_at, exclude_meeting_id=meeting_id
    )
    if verified.acknowledgements and earlier_open:
        p2_prompt = render_prompt(
            "match_acknowledgements",
            open_commitments="\n".join(_format_open_commitment(c) for c in earlier_open),
            meeting_date=meeting_date.isoformat(),
            acknowledgements="\n".join(
                _format_ack(i, a) for i, a in enumerate(verified.acknowledgements)
            ),
        )
        t0 = time.monotonic()
        matches = await llm.complete_json(p2_prompt, AckMatches, temperature=0.0)
        logger.info(
            "ingest p2 meeting=%s duration_ms=%d", meeting_id, int((time.monotonic() - t0) * 1000)
        )
        closed_ids = _match_commitment_ids(matches, earlier_open, len(verified.acknowledgements))

    # 6. Close matched commitments.
    for commitment_id in closed_ids:
        ingest_repo.mark_commitment_done(session, commitment_id, meeting_id)

    # 7. New commitments (after P2).
    rows: list[tuple[Owner, str | None, str, date | None, str]] = []
    for item in verified.commitments:
        contact = resolver.resolve(item.owner_person)
        rows.append(
            (
                item.owner,
                contact.id if contact else None,
                item.text.strip(),
                item.due_date,
                _clip(item.source_quote),
            )
        )
    created = ingest_repo.create_commitment_rows(
        session, account_id=account_id, meeting_id=meeting_id, rows=rows
    )

    # 8. Deal value: latest stated budget wins.
    facts = [f.text.strip() for f in verified.facts if f.text.strip()]
    budget = extraction.deal_budget_usd
    if budget is not None:
        previous = account.deal_value_usd
        ingest_repo.update_account_deal_value(session, account_id, budget)
        if previous is not None and previous != budget:
            facts.insert(0, f"Budget now {_format_usd(budget)} (was {_format_usd(previous)})")

    # 9. Retain. Any failure here leaves the meeting not ingested.
    t0 = time.monotonic()
    await memory.retain_meeting(
        meeting_id=meeting_id,
        account_id=account_id,
        contact_ids=attendee_ids,
        meeting_date=meeting_date,
        title=title,
        transcript=transcript,
        timeout_s=INGEST_RETAIN_TIMEOUT_S,
    )
    logger.info(
        "ingest retain meeting=%s duration_ms=%d", meeting_id, int((time.monotonic() - t0) * 1000)
    )

    # 10. Done only now.
    ingest_repo.set_meeting_ingested(session, meeting_id, ingest_repo.stamp())

    # 11. Summary (R2 alerts arrive with T20).
    return LearnedSummary(
        facts=facts,
        new_commitments=len(created),
        closed_commitments=len(closed_ids),
        alerts=[],
    )


def _describe_contact(contact: Contact) -> str:
    parts = [contact.name]
    if contact.aliases:
        parts.append(f"aliases: {', '.join(contact.aliases)}")
    if contact.role:
        parts.append(contact.role)
    return f"{parts[0]} ({'; '.join(parts[1:])})" if len(parts) > 1 else parts[0]
