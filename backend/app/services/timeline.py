"""Contact timeline (docs/technical-design.md "API routes"; ticket T18 / B18).

`memory.timeline(contact_id)` returns many near-duplicate facts per contact, so this
module turns them into a short, readable list:

1. Drop `kind:preference` hits, resolve the rest through `memory.resolve_sources`
   (observations carry no metadata), and drop hits with no meeting id or date.
2. `learned_on` is the meeting date from SQLite (fallback: the hit's own date).
3. Deduplicate near-identical facts. Duplicates are: equal normalised text, one
   containing the other (only when the shorter has `MIN_CONTAINMENT_WORDS` words, so a
   short fact like "Anita is the CFO" does not swallow a longer one), or word-set Jaccard
   >= `JACCARD_THRESHOLD`. The occurrence from the EARLIEST meeting is kept, because that
   is when the agent first learned the fact; ties keep Hindsight's rank order.
   Containment and Jaccard NEVER merge two texts whose "signatures" differ (a changed
   amount, date or contradicting fact must stay visible); see `signature`:
   a) numeric tokens (any token with a digit, number/ordinal words, month and weekday
      names) as a set; amounts are canonicalised first, so `$40K` == `$40,000` == `40000`;
   b) negation tokens (not, no, never, cannot, without, none, neither, nor, nobody,
      nothing, nowhere; `n't` forms are expanded to `not`) as a multiset;
   c) polarity labels from a short antonym list (`_POLARITY`) as a set.
4. Group by meeting: meetings newest first, all entries of a meeting adjacent, Hindsight
   rank order inside a meeting.
5. Cap at `MAX_ENTRIES`, cutting from the oldest end.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlmodel import Session

from app.core.errors import NotFoundError
from app.db import repository
from app.memory.memory_service import MemoryService
from app.memory.tags import MemoryKind, fact_kind_from_tags, kind_tag
from app.schemas.api import ContactRef, ContactTimeline, TimelineEntry
from app.schemas.brief import Citation, SourceType
from app.schemas.memory import MemoryHit
from app.services.evidence import call_label, truncate

MAX_ENTRIES = 30
QUOTE_MAX_CHARS = 200
JACCARD_THRESHOLD = 0.8
MIN_CONTAINMENT_WORDS = 5

_APOSTROPHES = re.compile(r"[’‘`]")
_NOT_CONTRACTIONS = (
    (re.compile(r"\bwon't\b"), "will not"),
    (re.compile(r"\bcan't\b"), "can not"),
    (re.compile(r"\bcannot\b"), "can not"),
    (re.compile(r"\bshan't\b"), "shall not"),
    (re.compile(r"n't\b"), " not"),
)
# 40, 40,000, 1.5, with an attached k/m/mm/bn/b or spaced thousand/million/billion suffix,
# and an optional ordinal suffix (15th). Not matched inside words such as `b2b` or `q3`.
_AMOUNT = re.compile(
    r"(?<![a-z0-9])(\d+(?:,\d{3})*(?:\.\d+)?)"
    r"(?:(k|mm|m|bn|b)(?![a-z0-9])|\s(thousand|million|billion)(?![a-z0-9]))?"
    r"(?:st|nd|rd|th)?(?![a-z0-9])"
)
_MULTIPLIERS = {
    "k": 10**3,
    "thousand": 10**3,
    "m": 10**6,
    "mm": 10**6,
    "million": 10**6,
    "b": 10**9,
    "bn": 10**9,
    "billion": 10**9,
}
_PUNCT = re.compile(r"[^a-z0-9\s]")

_NUMBER_WORDS = frozenset(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy "
    "eighty ninety hundred thousand million billion first second third fourth fifth sixth "
    "seventh eighth ninth tenth".split()
)
_MONTHS = {
    m: m
    for m in (
        "january february march april june july august september october november december"
    ).split()
} | {
    "may": "may",
    "jan": "january",
    "feb": "february",
    "mar": "march",
    "apr": "april",
    "jun": "june",
    "jul": "july",
    "aug": "august",
    "sep": "september",
    "sept": "september",
    "oct": "october",
    "nov": "november",
    "dec": "december",
}
_WEEKDAYS = {d: d for d in "monday tuesday wednesday thursday friday saturday sunday".split()} | {
    "tue": "tuesday",
    "tues": "tuesday",
    "wed": "wednesday",
    "thu": "thursday",
    "thur": "thursday",
    "thurs": "thursday",
    "fri": "friday",
}
# "may" is only a month next to a number or after one of these words.
_MAY_PRECEDERS = frozenset("in by of until till since from before after during this next".split())
_NEGATIONS = frozenset("not no never without none neither nor nobody nothing nowhere".split())
# Short, documented antonym list. Each word maps to one polarity label; two texts whose
# label sets differ are never merged. Words within a label are treated as paraphrases.
_POLARITY: dict[str, str] = {
    **dict.fromkeys(
        "increase increased increases increasing raise raised raises raising higher grow grew "
        "grown growing".split(),
        "up",
    ),
    **dict.fromkeys(
        "decrease decreased decreases decreasing reduce reduced reduces reducing lower lowered "
        "lowers lowering cut cuts drop dropped shrink shrank".split(),
        "down",
    ),
    **dict.fromkeys("approve approved approves approving accept accepted accepts".split(), "yes"),
    **dict.fromkeys(
        "reject rejected rejects deny denied denies decline declined refuse refused".split(), "no"
    ),
}


@dataclass(frozen=True)
class _Signature:
    numbers: frozenset[str]
    negations: tuple[str, ...]  # sorted multiset
    polarity: frozenset[str]


@dataclass(frozen=True)
class _Candidate:
    rank: int  # position in Hindsight's order
    hit: MemoryHit
    meeting_id: str
    learned_on: date
    norm: str
    words: frozenset[str]
    sig: _Signature


def _canonical_amount(match: re.Match[str]) -> str:
    value = Decimal(match.group(1).replace(",", ""))
    suffix = match.group(2) or match.group(3)
    if suffix:
        value *= _MULTIPLIERS[suffix]
    return f" {format(value.normalize(), 'f')} "


def normalise(text: str) -> str:
    """Lowercase; expand `n't` to `not`; canonicalise amounts (`$40K`, `$40,000` and
    `40000` all become `40000`, `15th` becomes `15`); drop apostrophes, turn other
    punctuation into spaces; collapse whitespace.
    """
    lowered = _APOSTROPHES.sub("'", text.lower())
    for pattern, replacement in _NOT_CONTRACTIONS:
        lowered = pattern.sub(replacement, lowered)
    lowered = _AMOUNT.sub(_canonical_amount, lowered)
    return " ".join(_PUNCT.sub(" ", lowered.replace("'", "")).split())


def signature(norm: str) -> _Signature:
    """Numbers, negations and polarity of an already-normalised text."""
    tokens = norm.split()
    numbers: set[str] = set()
    for i, token in enumerate(tokens):
        if any(ch.isdigit() for ch in token) or token in _NUMBER_WORDS:
            numbers.add(token)
        elif token in _WEEKDAYS:
            numbers.add(_WEEKDAYS[token])
        elif token in _MONTHS:
            is_may = token == "may"
            nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
            prev = tokens[i - 1] if i > 0 else ""
            if not is_may or nxt[:1].isdigit() or prev in _MAY_PRECEDERS:
                numbers.add(_MONTHS[token])
    return _Signature(
        numbers=frozenset(numbers),
        negations=tuple(sorted(t for t in tokens if t in _NEGATIONS)),
        polarity=frozenset(_POLARITY[t] for t in tokens if t in _POLARITY),
    )


def is_near_duplicate(a: _Candidate, b: _Candidate) -> bool:
    if a.norm == b.norm:
        return True
    if a.sig != b.sig:  # a changed amount/date, negation or polarity is new information
        return False
    shorter, longer = (a, b) if len(a.norm) <= len(b.norm) else (b, a)
    if len(shorter.words) >= MIN_CONTAINMENT_WORDS and f" {shorter.norm} " in f" {longer.norm} ":
        return True
    union = a.words | b.words
    return bool(union) and len(a.words & b.words) / len(union) >= JACCARD_THRESHOLD


def _dedupe_earliest(candidates: list[_Candidate]) -> list[_Candidate]:
    kept: list[_Candidate] = []
    for cand in sorted(candidates, key=lambda c: (c.learned_on, c.rank)):
        if not any(is_near_duplicate(cand, k) for k in kept):
            kept.append(cand)
    return kept


def _group_newest_first(candidates: list[_Candidate]) -> list[_Candidate]:
    return sorted(candidates, key=lambda c: (-c.learned_on.toordinal(), c.meeting_id, c.rank))


def _to_entry(cand: _Candidate) -> TimelineEntry:
    hit = cand.hit
    return TimelineEntry(
        text=hit.text,
        fact_kind=fact_kind_from_tags(hit.tags),
        learned_on=cand.learned_on,
        citation=Citation(
            source_type=SourceType.meeting,
            meeting_id=cand.meeting_id,
            meeting_date=cand.learned_on,
            label=call_label(cand.learned_on),
            quote=truncate(hit.text, QUOTE_MAX_CHARS),
            memory_id=hit.memory_id,
        ),
    )


async def build_timeline(
    contact_id: str, *, session: Session, memory: MemoryService
) -> ContactTimeline:
    """Raises `NotFoundError` for an unknown contact."""
    contact = repository.get_contact(session, contact_id)
    if contact is None:
        raise NotFoundError(f"Contact {contact_id!r} not found.")
    ref = ContactRef(id=contact.id, name=contact.name, role=contact.role)

    preference = kind_tag(MemoryKind.preference)
    hits = [h for h in await memory.timeline(contact_id) if preference not in h.tags]
    resolved = await memory.resolve_sources(hits)

    meeting_dates: dict[str, date | None] = {}
    candidates: list[_Candidate] = []
    for rank, hit in enumerate(resolved):
        if hit.meeting_id is None or hit.meeting_date is None:
            continue
        if hit.meeting_id not in meeting_dates:
            meeting = repository.get_meeting(session, hit.meeting_id)
            meeting_dates[hit.meeting_id] = meeting.scheduled_at.date() if meeting else None
        norm = normalise(hit.text)
        candidates.append(
            _Candidate(
                rank=rank,
                hit=hit,
                meeting_id=hit.meeting_id,
                learned_on=meeting_dates[hit.meeting_id] or hit.meeting_date,
                norm=norm,
                words=frozenset(norm.split()),
                sig=signature(norm),
            )
        )

    ordered = _group_newest_first(_dedupe_earliest(candidates))[:MAX_ENTRIES]
    return ContactTimeline(contact=ref, entries=[_to_entry(c) for c in ordered])
