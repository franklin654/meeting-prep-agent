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

from app.core.errors import AppError, MemoryUnavailableError, NotFoundError
from app.db import facts_repo, ingest_repo, repository
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
from app.services.reasoning import check_changes

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


_LABELLED_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|token|secret|authorization|password|passwd|key)"
    r"\s*[=:]\s*(?:(?:Basic|Bearer|Token)\s+)?\S+"
)
_SECRET_QUERY_PARAM = re.compile(r"(?i)[?&][^=\s&]*(?:key|token|secret|password)[^=\s&]*=[^&\s]*")
_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:Basic|Bearer|Token)\s+\S+"),
    re.compile(r"(?i)\b(?:sk|gsk|org|pk|rk)[-_][A-Za-z0-9_\-]{3,}"),
    re.compile(r"[A-Za-z0-9+/=_\-]{32,}"),
)


def safe_error_message(exc: BaseException) -> str:
    """Short, secret-free description of `exc` for the job row (never prompt/transcript text).

    Cuts at the first newline, `{` or the word "body" (case-insensitive; HTTP bodies can echo
    the request). Then redacts, before truncating to `ERROR_MESSAGE_MAX_CHARS`:
    `label=value` / `label: value` pairs for api key, token, secret, authorization and
    password labels (the whole pair becomes `label=<redacted>`); URL query parameters whose
    name contains key/token/secret/password; `Basic|Bearer|Token <value>`; key prefixes
    (sk-, gsk_, org-, pk-, rk-, sk_live_ ...); and any 32+ character base64-ish run.
    """
    text = re.split(r"(?i)\n|\{|\bbody\b", str(exc), maxsplit=1)[0].strip()
    text = _LABELLED_SECRET.sub(lambda m: f"{m.group(1)}=<redacted>", text)
    text = _SECRET_QUERY_PARAM.sub("?<redacted>", text)
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


def _has_deliverable_term(text: str) -> bool:
    return _has_term(f" {_normalize_name(text)} ", DELIVERABLE_ALLOW_TERMS)


def _merged_quote_member(
    kept: ExtractedCommitment,
    item: ExtractedCommitment,
    due: date | None,
    position: Callable[[ExtractedCommitment], int],
) -> ExtractedCommitment:
    """Member whose quote and speaker a merged commitment keeps (see `consolidate_commitments`)."""
    pool = [kept, item]
    carriers = [m for m in pool if m.due_date is not None and m.due_date == due]
    if len(carriers) == 1:
        return carriers[0]
    pool = carriers or pool
    named = [m for m in pool if _has_deliverable_term(m.source_quote)]
    if len(named) == 1:
        return named[0]
    return min(named or pool, key=position)  # min is stable: `kept` wins ties


def consolidate_commitments(
    commitments: Sequence[ExtractedCommitment], normalized_transcript: str = ""
) -> tuple[list[ExtractedCommitment], int, int]:
    """Drop logistics items, merge duplicates, then hard-cap at `MAX_COMMITMENTS_PER_MEETING`.

    Logistics items are dropped first so a dated recap can never outrank an undated real
    deliverable. Items citing the same normalized `source_quote` are one promise.

    Returns `(kept, merged_count, capped_count)`. A merged group keeps the longer (more
    specific) text and any due date (the earliest if several). Its quote comes from the member
    that carries the kept due date; else from the member whose quote names a deliverable
    (`DELIVERABLE_ALLOW_TERMS`); else the one earliest in the transcript (extraction order on
    ties). Dated commitments are kept first when capping, then extraction order.
    """

    def position(item: ExtractedCommitment) -> int:
        found = normalized_transcript.find(normalize_text(item.source_quote))
        return found if found >= 0 else len(normalized_transcript)

    groups: list[ExtractedCommitment] = []
    merged = 0
    for item in filter_logistics(commitments)[0]:
        for idx, kept in enumerate(groups):
            if _is_near_duplicate(kept, item):
                dues = [d for d in (kept.due_date, item.due_date) if d is not None]
                due = min(dues) if dues else None
                chosen = _merged_quote_member(kept, item, due, position)
                groups[idx] = chosen.model_copy(
                    update={
                        "text": max(kept.text, item.text, key=lambda t: len(t.strip())),
                        "due_date": due,
                        "owner_person": chosen.owner_person
                        or (item if chosen is kept else kept).owner_person,
                    }
                )
                merged += 1
                break
        else:
            groups.append(item)
    ordered = sorted(groups, key=lambda c: c.due_date is None)  # stable: dated first
    capped = max(0, len(ordered) - MAX_COMMITMENTS_PER_MEETING)
    return ordered[:MAX_COMMITMENTS_PER_MEETING], merged, capped


# ---- quote refinement ----

_MONTHS = (
    ("jan", "january"),
    ("feb", "february"),
    ("mar", "march"),
    ("apr", "april"),
    ("may", "may"),
    ("jun", "june"),
    ("jul", "july"),
    ("aug", "august"),
    ("sep", "september"),
    ("oct", "october"),
    ("nov", "november"),
    ("dec", "december"),
)
_RELATIVE_DATE_RE = re.compile(
    r"(?i)\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|today|"
    r"tonight|next week|this week|end of (?:the )?(?:day|week|month|quarter)|eod|eow)\b"
)
_UTTERANCE_RE = re.compile(
    r"^\[[^\]]*\]\s*(?P<speaker>[^:(]+?)\s*(?:\([^)]*\))?\s*:\s*(?P<text>.+)$"
)
_STOP_WORDS = frozenset(
    "a an and are as at be by for from has have i in is it its of on or our that the their "
    "them then there this to us was we will with you your ll send share prepare put get make "
    "also just".split()
)


def _explicit_date_patterns(due: date) -> list[re.Pattern[str]]:
    """Month-name+day (either order, optional ordinal suffix and dot) and ISO forms of `due`."""
    abbr, full = _MONTHS[due.month - 1]
    names = "|".join(sorted({abbr, full, "sept" if abbr == "sep" else abbr}, key=len, reverse=True))
    day = rf"0?{due.day}(?:st|nd|rd|th)?"
    return [
        re.compile(rf"(?i)\b(?:{names})\.?\s+{day}\b(?!\d)"),
        re.compile(rf"(?i)(?<!\d)\b{day}\s+(?:of\s+)?(?:{names})\b"),
        re.compile(rf"\b{due.isoformat()}\b"),
    ]


def _has_explicit_date(text: str, due: date) -> bool:
    return any(p.search(text) for p in _explicit_date_patterns(due))


def _carries_date_signal(quote: str, due: date) -> bool:
    """True if `quote` states `due` (month+day / ISO / ordinal day) or a relative date phrase."""
    if _has_explicit_date(quote, due):
        return True
    if re.search(rf"(?i)\b{due.day}(?:st|nd|rd|th)\b", quote):
        return True
    return bool(_RELATIVE_DATE_RE.search(quote))


def _content_words(text: str) -> frozenset[str]:
    return frozenset(
        w for w in _normalize_name(text).split() if len(w) > 2 and w not in _STOP_WORDS
    )


def _names_match(a: str, b: str) -> bool:
    """Name-only speaker comparison: equal, or one is a single token of the other."""
    na, nb = _normalize_name(a), _normalize_name(b)
    if not na or not nb:
        return False
    return na == nb or na in nb.split() or nb in na.split()


def _utterances(transcript: str) -> list[tuple[str, str]]:
    """`(speaker, text)` for each `[timestamp] Speaker (Role, Org): text` line, in order."""
    found: list[tuple[str, str]] = []
    for line in transcript.splitlines():
        match = _UTTERANCE_RE.match(line.strip())
        if match:
            found.append((match.group("speaker").strip(), match.group("text").strip()))
    return found


def _utterance_quote(text: str, due: date) -> str:
    """The full utterance if it fits in 200 chars, else the sentence carrying the date."""
    if len(text) <= MAX_QUOTE_CHARS:
        return text
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if _has_explicit_date(sentence, due):
            return _clip(sentence)
    return _clip(text)


def refine_quotes(
    commitments: Sequence[ExtractedCommitment],
    transcript: str,
    same_speaker: Callable[[str, str], bool] = _names_match,
) -> tuple[list[ExtractedCommitment], int]:
    """Re-point a dated commitment's quote at the sentence that carries its due date.

    Only for commitments with a `due_date` whose `source_quote` has no date signal (see
    `_carries_date_signal`). Searches the transcript in order for the earliest utterance by the
    same speaker (`owner_person` via `same_speaker(owner_person, speaker)`, or the speaker of
    the current quote) that (a) states the due date as month-name+day or ISO, (b) is not a
    question (ends with "?") and (c) names a deliverable (`DELIVERABLE_ALLOW_TERMS`) or shares a
    content word with the commitment text. Candidates sharing a content word win over ones with
    only a deliverable term; among equals the earliest wins.
    The replacement is verbatim from the transcript (<= 200 chars). Otherwise the quote is
    kept. Text, owner and due date never change. Returns `(commitments, refined_count)`.
    """
    utterances = _utterances(transcript)
    normalized = normalize_text(transcript)
    result: list[ExtractedCommitment] = []
    refined = 0
    for item in commitments:
        due = item.due_date
        if due is None or _carries_date_signal(item.source_quote, due):
            result.append(item)
            continue
        quote_norm = normalize_text(item.source_quote)
        current_speaker = next(
            (spk for spk, text in utterances if quote_norm in normalize_text(text)), None
        )
        words = _content_words(item.text)
        shared: str | None = None  # earliest candidate sharing a content word with the text
        named: str | None = None  # earliest candidate with only a deliverable term
        for speaker, text in utterances:
            speaker_ok = same_speaker(item.owner_person, speaker) or (
                current_speaker is not None and _names_match(current_speaker, speaker)
            )
            if text.rstrip().endswith("?") or not speaker_ok or not _has_explicit_date(text, due):
                continue  # a question is not a promise
            has_shared_word = bool(_content_words(text) & words)
            if not has_shared_word and not _has_deliverable_term(text):
                continue
            candidate = _utterance_quote(text, due)
            if not is_verbatim(candidate, normalized):
                continue
            if has_shared_word:
                shared = candidate
                break
            if named is None:
                named = candidate
        replacement = shared or named
        if replacement is None:
            result.append(item)
        else:
            result.append(item.model_copy(update={"source_quote": replacement}))
            refined += 1
    return result, refined


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


def _match_renewed_commitments(
    matches: AckMatches,
    open_commitments: Sequence[Commitment],
    new_commitments: Sequence[ExtractedCommitment],
    resolver: _Resolver,
) -> dict[str, int]:
    """Accept only P2 renewals whose owner and deliverable match an existing open row."""
    open_by_id = {commitment.id: commitment for commitment in open_commitments}
    accepted: dict[str, int] = {}
    used_new_indexes: set[int] = set()
    dropped = 0
    for match in matches.renewed:
        existing = open_by_id.get(match.commitment_id)
        if (
            existing is None
            or match.commitment_index < 0
            or match.commitment_index >= len(new_commitments)
            or match.commitment_id in accepted
            or match.commitment_index in used_new_indexes
        ):
            dropped += 1
            continue
        candidate = new_commitments[match.commitment_index]
        owner_contact = resolver.find(candidate.owner_person)
        if (
            candidate.due_date is None
            or candidate.owner != existing.owner
            or owner_contact is None
            or owner_contact.id != existing.contact_id
        ):
            dropped += 1
            continue
        prior = ExtractedCommitment(
            owner=existing.owner,
            owner_person=owner_contact.name,
            text=existing.text,
            due_date=existing.due_date,
            source_quote=existing.source_quote,
        )
        comparable = candidate.model_copy(update={"owner_person": owner_contact.name})
        if not _is_near_duplicate(prior, comparable):
            dropped += 1
            continue
        accepted[existing.id] = match.commitment_index
        used_new_indexes.add(match.commitment_index)
    if dropped:
        logger.warning("ingest p2 dropped_invalid_renewals=%d", dropped)
    return accepted


def _format_open_commitment(commitment: Commitment, owner_name: str | None = None) -> str:
    """`id: text | original words: "quote"`, so P2 can match an acknowledgement that uses
    different words than the commitment's text (docs: quote truncated to 200 chars)."""
    quote = " ".join(commitment.source_quote.split())[:MAX_QUOTE_CHARS]
    owner = f"{commitment.owner.value} ({owner_name})" if owner_name else commitment.owner.value
    return f'{commitment.id}: {commitment.text} | owner: {owner} | original words: "{quote}"'


def _format_new_commitment(index: int, commitment: ExtractedCommitment) -> str:
    due = commitment.due_date.isoformat() if commitment.due_date else "unspecified"
    return (
        f"{index}: owner: {commitment.owner.value}, person: {commitment.owner_person}, "
        f"text: {commitment.text}, due: {due}"
    )


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

    def same_speaker(owner: str, speaker: str) -> bool:
        a, b = resolver.find(owner), resolver.find(speaker)
        return a.id == b.id if a is not None and b is not None else _names_match(owner, speaker)

    verified.commitments, quote_refined = refine_quotes(
        verified.commitments, transcript, same_speaker
    )
    if quote_refined:
        logger.info("ingest commitments quote_refined=%d meeting=%s", quote_refined, meeting_id)

    # 5. P2, against open commitments from earlier meetings only.
    closed_ids: list[str] = []
    renewed: dict[str, int] = {}
    earlier_open = ingest_repo.list_open_commitments(
        session, account_id, before=scheduled_at, exclude_meeting_id=meeting_id
    )
    if earlier_open and (verified.acknowledgements or verified.commitments):
        open_lines = []
        for commitment in earlier_open:
            owner = session.get(Contact, commitment.contact_id) if commitment.contact_id else None
            open_lines.append(
                _format_open_commitment(commitment, owner.name if owner is not None else None)
            )
        p2_prompt = render_prompt(
            "match_acknowledgements",
            open_commitments="\n".join(open_lines),
            new_commitments="\n".join(
                _format_new_commitment(i, item) for i, item in enumerate(verified.commitments)
            )
            or "(none)",
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
        renewed = _match_renewed_commitments(matches, earlier_open, verified.commitments, resolver)
        closed_ids = [commitment_id for commitment_id in closed_ids if commitment_id not in renewed]

    # 6. Close matched commitments.
    for commitment_id in closed_ids:
        ingest_repo.mark_commitment_done(session, commitment_id, meeting_id)

    renewed_indexes: set[int] = set()
    for commitment_id, commitment_index in renewed.items():
        due_date = verified.commitments[commitment_index].due_date
        assert due_date is not None
        if ingest_repo.update_open_commitment_due_date(session, commitment_id, due_date):
            renewed_indexes.add(commitment_index)

    # 7. New commitments (after P2).
    rows: list[tuple[Owner, str | None, str, date | None, str]] = []
    for commitment_index, item in enumerate(verified.commitments):
        if commitment_index in renewed_indexes:
            continue
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

    fact_rows = []
    for fact_item in verified.facts:
        text = fact_item.text.strip()
        if not text:
            continue
        contact = resolver.find(fact_item.about_person) if fact_item.about_person else None
        fact_rows.append(
            (
                contact.id if contact else None,
                fact_item.kind,
                text,
                _clip(fact_item.source_quote),
            )
        )
    facts_repo.replace_meeting_facts(session, meeting_id, account_id, fact_rows)

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

    if not await memory.wait_until_idle(timeout_s=60.0):
        raise MemoryUnavailableError("Hindsight did not become idle before contradiction analysis.")
    alerts = await check_changes(
        memory=memory,
        account_id=account_id,
        account_name=account_name,
        meeting_id=meeting_id,
        meeting_date=meeting_date,
    )

    # 10. Done only now.
    ingest_repo.set_meeting_ingested(session, meeting_id, ingest_repo.stamp())

    # 11. Summary (R2 alerts arrive with T20).
    return LearnedSummary(
        facts=facts,
        new_commitments=len(created),
        closed_commitments=len(closed_ids),
        alerts=alerts,
    )


def _describe_contact(contact: Contact) -> str:
    parts = [contact.name]
    if contact.aliases:
        parts.append(f"aliases: {', '.join(contact.aliases)}")
    if contact.role:
        parts.append(contact.role)
    return f"{parts[0]} ({'; '.join(parts[1:])})" if len(parts) > 1 else parts[0]
