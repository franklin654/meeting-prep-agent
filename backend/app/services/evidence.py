"""Evidence assembly for the brief prompt (docs/prompt-specs.md P3 "Evidence assembly").

Pure code, no I/O. Turns memory hits, reflect output, the ledger and the mental model
into a numbered evidence list with short ids (`mm:1`, `mem:1`, `led:1`, `ask:1`) and a
code-side table mapping each id back to what it may cite. The LLM only ever sees the
rendered lines; citations are built from the table, never from model output.

Order: mental model, recall hits, reflect outputs, ledger rows, pinned Ask answers
(none yet). Recall and reflect entries keep the order they arrive in (Hindsight's
relevance rank, section priority first), NOT recency. Capped at `EVIDENCE_CAP`: the mental
model and the dated ledger rows are never cut; recall and reflect entries fill the rest.
Ledger evidence is only overdue dated rows plus at most `MAX_UPCOMING_LEDGER_ROWS` dated
upcoming ones; undated rows never reach the prompt.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel, ConfigDict

from app.db.models import Commitment
from app.memory.memory_service import MentalModelText
from app.schemas.brief import SourceType
from app.schemas.memory import MemoryHit

logger = logging.getLogger(__name__)

EVIDENCE_CAP = 25
MAX_UPCOMING_LEDGER_ROWS = 5
MAX_OVERDUE_EVIDENCE = 8
MIN_RECALL = 8
QUOTE_MAX_CHARS = 200
PROMPT_TEXT_MAX_CHARS = 160
PROMPT_MENTAL_MODEL_MAX_CHARS = 500


# ---- R1 output model (prompt: reflect_objections.md) ----
class Objection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    concern: str
    raised_by: str
    raised_on: date
    resolved: bool
    resolution: str | None = None


class ObjectionReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    objections: list[Objection]


@dataclass(frozen=True)
class MeetingInfo:
    """What evidence needs to know about a meeting, read from SQLite."""

    id: str
    title: str
    date: date


class EvidenceRef(BaseModel):
    key: str  # short id shown to the LLM: "mem:1"
    source_type: SourceType
    meeting_id: str | None
    meeting_date: date | None
    quote: str | None
    memory_id: str | None
    text: str  # prompt-facing line body
    label: str
    commitment_id: str | None = None
    overdue: bool = False
    owner: str | None = None  # ledger rows: "us" | "them"
    due_date: date | None = None  # ledger rows
    kind: str | None = None
    account_id: str | None = None


class EvidenceTable:
    def __init__(self, refs: Sequence[EvidenceRef]) -> None:
        self.refs = list(refs)
        self._by_key = {r.key: r for r in self.refs}

    def get(self, key: str) -> EvidenceRef | None:
        return self._by_key.get(key.strip().strip("[]"))

    def render(self) -> str:
        """One compact line per evidence entry; `(none)` when empty."""
        if not self.refs:
            return "(none)"
        return "\n".join(f"[{r.key}] {r.text}" for r in self.refs)


def truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def format_date(d: date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def call_label(d: date) -> str:
    return f"Call on {format_date(d)}"


def _words(text: str) -> set[str]:
    return {w.strip(".,;:!?\"'()").lower() for w in text.split() if len(w) > 3}


def match_objection_sources(
    report: ObjectionReport, sources: Sequence[MemoryHit]
) -> list[tuple[Objection, MemoryHit]]:
    """Pair each UNRESOLVED objection with the resolved source memory that supports it.

    The structured objection has no meeting id, so it cannot be cited by itself. Pick the
    source (with a resolved meeting) sharing the most words with the concern; failing
    that, one whose meeting date equals `raised_on`. An objection with no supporting
    source is dropped: it has nothing to cite.
    """
    usable = [s for s in sources if s.meeting_id is not None]
    pairs: list[tuple[Objection, MemoryHit]] = []
    for objection in report.objections:
        if objection.resolved:
            continue
        target = _words(f"{objection.concern} {objection.raised_by}")
        scored = [(len(target & _words(s.text)), s) for s in usable]
        best_score, best = max(scored, key=lambda p: p[0], default=(0, None))
        if best is None or best_score == 0:
            best = next((s for s in usable if s.meeting_date == objection.raised_on), None)
        if best is None:
            logger.info("brief.objection_dropped reason=no_supporting_source")
            continue
        pairs.append((objection, best))
    return pairs


def build_evidence(
    *,
    mental_model: MentalModelText | None,
    latest_ingested_meeting: MeetingInfo | None,
    recall_hits: Sequence[MemoryHit] = (),
    objections: Sequence[tuple[Objection, MemoryHit]],
    commitments: Sequence[Commitment],
    meetings: Mapping[str, MeetingInfo],
    today: date,
    cap: int = EVIDENCE_CAP,
    recall_sections: Sequence[Sequence[MemoryHit]] | None = None,
    objection_hits: Sequence[MemoryHit] = (),
    cross_deal_hits: Sequence[MemoryHit] = (),
) -> EvidenceTable:
    """Assemble the capped, numbered evidence table.

    `commitments` are the account's OPEN ledger rows. Recall hits and objection sources
    must already be resolved (`MemoryService.resolve_sources`); any without a `meeting_id`
    are unusable as evidence and skipped. A meeting's date comes from SQLite when the
    meeting is known there, else from the hit.

    `recall_sections` holds one hit list per recall section (watch-outs, then one per external
    attendee), each in Hindsight rank order; `recall_hits` is a single-section shorthand.

    Slot arithmetic (defaults: cap 25, mental model 1, overdue <= 8, upcoming <= 5, so the
    protected entries are at most 14 and 11 slots remain):
      * recall floor = max(sections with usable hits, min(MIN_RECALL, usable recall entries));
        with the defaults 14 + 8 = 22 <= 25, so the floor always fits the cap;
      * reflect (objection) entries take the slots left after the floor;
      * recall then takes whatever remains (never fewer than its floor).
    The floor takes each section's top hit first, then fills by section priority and rank.
    Only with more than 11 recall sections could the total pass the cap.
    """
    sections = list(recall_sections) if recall_sections is not None else [recall_hits]
    protected: list[EvidenceRef] = []

    # The summary has no meeting of its own: it is cited to the account's latest INGESTED
    # meeting (what the memory has read up to), and dropped when nothing is ingested yet.
    if mental_model is not None and mental_model.content.strip() and latest_ingested_meeting:
        content = mental_model.content.strip()
        protected.append(
            EvidenceRef(
                key="",
                source_type=SourceType.mental_model,
                meeting_id=latest_ingested_meeting.id,
                meeting_date=latest_ingested_meeting.date,
                quote=truncate(content, QUOTE_MAX_CHARS),
                memory_id=mental_model.id,
                text="Relationship summary: " + truncate(content, PROMPT_MENTAL_MODEL_MAX_CHARS),
                label=(
                    f"{latest_ingested_meeting.title} · "
                    f"{latest_ingested_meeting.date:%b} {latest_ingested_meeting.date.day}"
                ),
            )
        )

    section_refs: list[list[EvidenceRef]] = []
    seen_ids: set[str] = set()
    for hits in sections:
        refs = [r for r in _memory_refs(hits, meetings, prefix=None) if r.memory_id not in seen_ids]
        seen_ids.update(r.memory_id for r in refs if r.memory_id)
        section_refs.append(refs)
    recalled_objections = _memory_refs(
        objection_hits,
        meetings,
        prefix=[
            f"Unresolved objection: {truncate(hit.text, PROMPT_TEXT_MAX_CHARS)}"
            for hit in objection_hits
        ],
    )
    if recalled_objections:
        section_refs.append(recalled_objections)
    cross_refs = [
        ref
        for ref in _memory_refs(cross_deal_hits, meetings, prefix=None, kind="cross_deal")
        if ref.memory_id not in seen_ids
    ]
    if cross_refs:
        section_refs.append(cross_refs)
    reflect_refs = _memory_refs(
        [hit for _, hit in objections],
        meetings,
        prefix=[
            f"Unresolved concern ({o.raised_by}): {truncate(o.concern, PROMPT_TEXT_MAX_CHARS)}"
            for o, _ in objections
        ],
    )
    ledger_refs = _ledger_refs(commitments, meetings, today)

    recall_total = sum(len(r) for r in section_refs)
    floor = max(sum(1 for r in section_refs if r), min(MIN_RECALL, recall_total))
    available = max(0, cap - len(protected) - len(ledger_refs))
    reflect_kept = reflect_refs[: max(0, available - floor)]
    recall_kept = _pick_recall(section_refs, max(floor, available - len(reflect_kept)))
    logger.debug(
        "brief.evidence recall_in=%d recall_kept=%d reflect_in=%d reflect_kept=%d "
        "ledger=%d total=%d",
        sum(len(h) for h in sections) + len(objection_hits) + len(cross_deal_hits),
        len(recall_kept),
        len(objections),
        len(reflect_kept),
        len(ledger_refs),
        len(protected) + len(recall_kept) + len(reflect_kept) + len(ledger_refs),
    )
    dropped = recall_total + len(reflect_refs) - len(recall_kept) - len(reflect_kept)
    if dropped > 0:
        logger.info(
            "brief.evidence_capped kept=%d dropped=%d",
            len(recall_kept) + len(reflect_kept),
            dropped,
        )

    ordered = [*protected, *recall_kept, *reflect_kept, *ledger_refs]
    counters = {"mm": 0, "mem": 0, "cross_deal": 0, "led": 0, "ask": 0}
    prefix_of = {
        SourceType.mental_model: "mm",
        SourceType.meeting: "mem",
        SourceType.ledger: "led",
        SourceType.ask: "ask",
    }
    numbered: list[EvidenceRef] = []
    for ref in ordered:
        p = "cross_deal" if ref.kind == "cross_deal" else prefix_of[ref.source_type]
        counters[p] += 1
        numbered.append(ref.model_copy(update={"key": f"{p}:{counters[p]}"}))
    return EvidenceTable(numbered)


def _pick_recall(section_refs: Sequence[Sequence[EvidenceRef]], slots: int) -> list[EvidenceRef]:
    """`slots` recall entries: each section's top hit first (the floor), then the rest by
    section priority and rank. Output keeps section order, then rank within a section."""
    chosen: set[tuple[int, int]] = {(si, 0) for si, refs in enumerate(section_refs) if refs}
    for si, refs in enumerate(section_refs):
        for pi in range(len(refs)):
            if len(chosen) >= slots:
                break
            chosen.add((si, pi))
    return [
        refs[pi]
        for si, refs in enumerate(section_refs)
        for pi in range(len(refs))
        if (si, pi) in chosen
    ]


def _memory_refs(
    hits: Sequence[MemoryHit],
    meetings: Mapping[str, MeetingInfo],
    *,
    prefix: Sequence[str] | None,
    kind: str | None = None,
) -> list[EvidenceRef]:
    seen: set[str] = set()
    refs: list[EvidenceRef] = []
    for i, hit in enumerate(hits):
        if hit.meeting_id is None or (prefix is None and hit.memory_id in seen):
            continue
        info = meetings.get(hit.meeting_id)
        meeting_date = info.date if info is not None else hit.meeting_date
        if meeting_date is None:
            continue
        seen.add(hit.memory_id)
        label = (
            f"{info.title} · {meeting_date:%b} {meeting_date.day}"
            if info
            else call_label(meeting_date)
        )
        body = prefix[i] if prefix is not None else truncate(hit.text, PROMPT_TEXT_MAX_CHARS)
        source_account = next(
            (tag.removeprefix("account:") for tag in hit.tags if tag.startswith("account:")),
            None,
        )
        if kind == "cross_deal":
            body = f"cross_deal evidence ({label}): {body}"
        refs.append(
            EvidenceRef(
                key="",
                source_type=SourceType.meeting,
                meeting_id=hit.meeting_id,
                meeting_date=meeting_date,
                quote=truncate(hit.text, QUOTE_MAX_CHARS),
                memory_id=hit.memory_id,
                text=f"({label}) {body}",
                label=label,
                kind=kind,
                account_id=source_account,
            )
        )
    return refs


def _ledger_refs(
    commitments: Sequence[Commitment], meetings: Mapping[str, MeetingInfo], today: date
) -> list[EvidenceRef]:
    dated = [c for c in commitments if c.due_date is not None]
    # At most MAX_OVERDUE_EVIDENCE overdue rows go to the prompt: the most recently due (they
    # are the freshest; ties broken by id so the choice is deterministic), shown oldest first.
    # Any overdue row left out is still put in the brief by the forced-overdue appender.
    overdue_all = [c for c in dated if c.due_date is not None and c.due_date < today]
    latest_overdue = sorted(overdue_all, key=lambda c: (c.due_date or date.min, c.id), reverse=True)
    overdue_rows = sorted(
        latest_overdue[:MAX_OVERDUE_EVIDENCE], key=lambda c: (c.due_date or date.max, c.id)
    )
    upcoming_rows = sorted(
        (c for c in dated if c.due_date is not None and c.due_date >= today),
        key=lambda c: c.due_date or date.max,
    )[:MAX_UPCOMING_LEDGER_ROWS]
    refs: list[EvidenceRef] = []
    for c in [*overdue_rows, *upcoming_rows]:
        info = meetings.get(c.meeting_id)
        if info is None:
            continue
        overdue = c.due_date is not None and c.due_date < today
        status = "OPEN, OVERDUE" if overdue else "OPEN"
        due = f", due {c.due_date.isoformat()}" if c.due_date else ""
        label = f"{info.title} · {info.date:%b} {info.date.day}"
        refs.append(
            EvidenceRef(
                key="",
                source_type=SourceType.ledger,
                meeting_id=info.id,
                meeting_date=info.date,
                quote=truncate(c.source_quote, QUOTE_MAX_CHARS),
                memory_id=None,
                text=(
                    f"{status}: {c.owner.value} -> {truncate(c.text, PROMPT_TEXT_MAX_CHARS)}"
                    f"{due} ({call_label(info.date)})"
                ),
                label=label,
                commitment_id=c.id,
                overdue=overdue,
                owner=c.owner.value,
                due_date=c.due_date,
            )
        )
    return refs
