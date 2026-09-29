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
4. Group by meeting: meetings newest first, all entries of a meeting adjacent, Hindsight
   rank order inside a meeting.
5. Cap at `MAX_ENTRIES`, cutting from the oldest end.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

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

_NON_WORD = re.compile(r"[^a-z0-9\s]")


@dataclass(frozen=True)
class _Candidate:
    rank: int  # position in Hindsight's order
    hit: MemoryHit
    meeting_id: str
    learned_on: date
    norm: str
    words: frozenset[str]


def normalise(text: str) -> str:
    """Lowercase, drop punctuation (so `$40,000` becomes `40000`), collapse whitespace."""
    return " ".join(_NON_WORD.sub("", text.lower()).split())


def is_near_duplicate(a: _Candidate, b: _Candidate) -> bool:
    if a.norm == b.norm:
        return True
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
            )
        )

    ordered = _group_newest_first(_dedupe_earliest(candidates))[:MAX_ENTRIES]
    return ContactTimeline(contact=ref, entries=[_to_entry(c) for c in ordered])
