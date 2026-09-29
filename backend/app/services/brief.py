"""Brief service (docs/technical-design.md "Brief (before a meeting)", prompt P3).

`generate_brief(meeting_id, mode, ...)`:
    1. load meeting, attendees, account, ledger from SQLite;
    2. (memory mode) gather concurrently: mental model, personal recalls per external
       attendee, competitor recall, R1 objections reflect (sources resolved to meetings);
       a failing memory call degrades only its own section;
    3. build the numbered evidence table in code (`services/evidence.py`);
    4. ONE P3 call (`assemble_brief.md`);
    5. post-process in code: citations from the table, unresolved ids dropped, uncited
       items dropped in memory mode, overdue severity forced, missing overdue items
       appended, attendees section built from SQLite + transcripts (not by the LLM);
    6. upsert the `BriefRecord` for the meeting and mode.

`no_memory` mode runs the SAME prompt with an empty evidence list and makes no memory
or ledger calls; every item has zero citations.

Design choices where the docs are silent are listed in the ticket report.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import ValidationError as PydanticValidationError

from app.core.errors import MemoryUnavailableError, ValidationError
from app.core.time import today
from app.db.brief_repo import (
    BriefInputs,
    SessionFactory,
    get_fresh_brief,
    load_brief_inputs,
    new_brief_stamp,
    save_brief,
)
from app.db.models import Commitment, Contact, Meeting
from app.llm.client import LLMClient, get_llm_client
from app.llm.prompt_loader import render_prompt
from app.memory.memory_service import MemoryService, MentalModelText, _relationship_model_id
from app.memory.tags import account_tag, contact_tag
from app.schemas.brief import (
    Brief,
    BriefDraft,
    BriefItem,
    BriefSection,
    Citation,
    SectionKey,
    Severity,
    SourceType,
)
from app.schemas.enums import FactKind
from app.schemas.memory import MemoryHit
from app.services.evidence import (
    QUOTE_MAX_CHARS,
    EvidenceRef,
    EvidenceTable,
    MeetingInfo,
    Objection,
    ObjectionReport,
    build_evidence,
    call_label,
    format_date,
    match_objection_sources,
    truncate,
)

logger = logging.getLogger(__name__)

BriefMode = Literal["memory", "no_memory"]

# P3 is the biggest call in the app (a spike measured ~17-23 s at 43 evidence items), so it
# gets its own client timeout; the app default (30 s) is unchanged elsewhere. If it is
# exceeded the client raises `llm_timeout` and the brief fails: no retries of ours.
BRIEF_LLM_TIMEOUT_SECONDS = 120
BRIEF_TEMPERATURE = 0.3

# Style profile is the default until Phase 4 adds learning from feedback.
DEFAULT_STYLE_PROFILE = "default"
DEFAULT_SECTION_ORDER: list[SectionKey] = list(SectionKey)

# Sections the LLM writes. `attendees` is built in code; `your_questions` renders pinned
# Ask answers, which do not exist yet.
LLM_SECTION_KEYS: list[SectionKey] = [
    SectionKey.where_left_off,
    SectionKey.open_commitments,
    SectionKey.unresolved_objections,
    SectionKey.personal_touchpoints,
    SectionKey.agenda,
    SectionKey.watch_outs,
    SectionKey.alerts,
]

SECTION_TITLES: dict[SectionKey, str] = {
    SectionKey.attendees: "Attendees",
    SectionKey.where_left_off: "Where we left off",
    SectionKey.open_commitments: "Open commitments",
    SectionKey.unresolved_objections: "Unresolved objections",
    SectionKey.personal_touchpoints: "Personal touchpoints",
    SectionKey.agenda: "Suggested agenda",
    SectionKey.watch_outs: "Watch-outs",
    SectionKey.alerts: "Alerts",
    SectionKey.your_questions: "Your questions",
}

# Sections whose items are never below `warning` (prompt rule, enforced in code).
_WARNING_FLOOR = {SectionKey.watch_outs, SectionKey.alerts}


def default_brief_llm() -> LLMClient:
    """The LLM client for P3: the configured provider with the 120 s brief timeout."""
    return get_llm_client(timeout_seconds=BRIEF_LLM_TIMEOUT_SECONDS)


# ---- persona ----------------------------------------------------------------------


@dataclass(frozen=True)
class Persona:
    user_name: str
    our_company: str


_COMPANY_JSON = Path(__file__).resolve().parents[3] / "data" / "seed" / "company.json"


@lru_cache(maxsize=1)
def load_persona() -> Persona:
    """The seeded persona (AE name, our company) from `data/seed/company.json`.

    Never derived from `settings.demo_user_id` or the bank id.
    """
    if not _COMPANY_JSON.is_file():
        raise FileNotFoundError(
            f"Persona file not found: {_COMPANY_JSON}. The brief needs data/seed/company.json "
            "(ae.name and vendor.name); make sure the repo's data/ directory is available."
        )
    data = json.loads(_COMPANY_JSON.read_text(encoding="utf-8"))
    return Persona(user_name=data["ae"]["name"], our_company=data["vendor"]["name"])


# ---- transcript line parser --------------------------------------------------------

# "[2026-08-27T10:00:08+05:30] Priya Nair (Account Executive, Tracewise): text"
_LINE = re.compile(r"^\[[^\]]+\]\s+(?P<speaker>.+?)\s+\((?P<role>[^)]*)\):\s*(?P<text>\S.*)$")


def first_line_spoken_by(transcript: str | None, names: Sequence[str]) -> str | None:
    """The words of the first transcript line spoken by any of `names` (case-insensitive)."""
    if not transcript:
        return None
    wanted = {n.casefold() for n in names if n}
    for raw in transcript.splitlines():
        match = _LINE.match(raw.strip())
        if match and match.group("speaker").casefold() in wanted:
            return match.group("text").strip()
    return None


# ---- memory gathering --------------------------------------------------------------


@dataclass
class MemoryContext:
    mental_model: MentalModelText | None = None
    recall_hits: list[MemoryHit] = field(default_factory=list)
    objections: list[tuple[Objection, MemoryHit]] = field(default_factory=list)


TOP_HITS_PER_QUERY = 3

# Generic wording only: no fixture names, so the same queries work for any account.
PERSONAL_QUERY = "personal life: family, children, hobbies, travel, milestones, non-work interests"
COMPETITOR_QUERY = (
    "competitors or alternative vendors the customer has evaluated or is comparing us against"
)


def _normalize(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def top_distinct_hits(
    hits: Sequence[MemoryHit], limit: int = TOP_HITS_PER_QUERY
) -> list[MemoryHit]:
    """First `limit` hits in the order given (Hindsight's relevance rank, never re-sorted by
    date), skipping duplicates: equal after lowercasing/punctuation removal, or one text
    contained in another.
    """
    kept: list[MemoryHit] = []
    norms: list[str] = []
    for hit in hits:
        norm = _normalize(hit.text)
        if not norm or any(norm in other or other in norm for other in norms):
            continue
        kept.append(hit)
        norms.append(norm)
        if len(kept) == limit:
            break
    return kept


async def _recall_top(
    memory: MemoryService,
    *,
    section: str,
    query: str,
    tags: list[str],
    fact_kind: FactKind,
    fallback_query: str | None = None,
) -> list[MemoryHit]:
    """Labelled recall; if it returns nothing, ONE retry without `fact_kind` (the extraction
    model does not always label facts). Top hits are then resolved to meetings.
    """
    hits = await memory.recall_facts(query=query, tags=tags, fact_kind=fact_kind)
    fell_back = False
    if not hits:
        fell_back = True
        hits = await memory.recall_facts(query=fallback_query or query, tags=tags)
    kept = top_distinct_hits(hits)
    resolved = await memory.resolve_sources(kept)
    logger.debug(
        "brief.recall section=%s returned=%d kept=%d fallback=%s resolved=%d",
        section,
        len(hits),
        len(kept),
        fell_back,
        sum(1 for h in resolved if h.meeting_id is not None),
    )
    return resolved


async def _objection_evidence(
    memory: MemoryService, *, account_id: str, account_name: str, today_: date
) -> list[tuple[Objection, MemoryHit]]:
    query = render_prompt("reflect_objections", today=today_.isoformat(), account_name=account_name)
    result = await memory.reflect_structured(
        query=query, tags=[account_tag(account_id)], schema=ObjectionReport
    )
    if result.structured is None:
        logger.warning(
            "brief.section_dropped section=unresolved_objections reason=%s",
            result.structured_error or "no structured output",
        )
        return []
    try:
        report = ObjectionReport.model_validate(result.structured)
    except PydanticValidationError:
        logger.warning("brief.section_dropped section=unresolved_objections reason=invalid_output")
        return []
    sources = await memory.resolve_sources(result.sources)
    return match_objection_sources(report, sources)


async def _gather_memory(inputs: BriefInputs, memory: MemoryService, today_: date) -> MemoryContext:
    account = inputs.account
    external = [c for c in inputs.attendees if c.account_id is not None]

    results = await asyncio.gather(
        memory.get_mental_model(_relationship_model_id(account.id)),
        _objection_evidence(
            memory, account_id=account.id, account_name=account.name, today_=today_
        ),
        _recall_top(
            memory,
            section="watch_outs",
            query=COMPETITOR_QUERY,
            tags=[account_tag(account.id)],
            fact_kind=FactKind.competitor,
        ),
        *(
            _recall_top(
                memory,
                section=f"personal_touchpoints:{c.id}",
                query=f"{c.name} {PERSONAL_QUERY}",
                tags=[contact_tag(c.id)],
                fact_kind=FactKind.personal,
            )
            for c in external
        ),
        return_exceptions=True,
    )
    labels = ["mental_model", "unresolved_objections", "watch_outs"]
    labels += [f"personal_touchpoints:{c.id}" for c in external]

    failed = 0
    for label, result in zip(labels, results, strict=True):
        if isinstance(result, MemoryUnavailableError):
            failed += 1
            logger.warning("brief.section_degraded section=%s error=%s", label, result.message)
        elif isinstance(result, BaseException):
            raise result  # a bug or a non-memory error must not be swallowed

    mental_model, objections, *recalls = results
    context = MemoryContext()
    if isinstance(mental_model, MentalModelText):
        context.mental_model = mental_model
    if isinstance(objections, list):
        context.objections = [p for p in objections if isinstance(p, tuple)]
    for recall in recalls:
        if isinstance(recall, list):
            context.recall_hits.extend(h for h in recall if isinstance(h, MemoryHit))
    if failed == len(results):
        raise MemoryUnavailableError("Every memory call for the brief failed.")
    return context


# ---- prompt ------------------------------------------------------------------------


def render_brief_prompt(*, persona: Persona, inputs: BriefInputs, evidence_text: str) -> str:
    """Render P3. `no_memory` mode differs from `memory` mode only in `evidence_text`."""
    attendees = "; ".join(
        f"{c.id}: {c.name}" + (f" ({c.role})" if c.role else "") for c in inputs.attendees
    )
    return render_prompt(
        "assemble_brief",
        user_name=persona.user_name,
        our_company=persona.our_company,
        today=today().isoformat(),
        meeting_title=inputs.meeting.title,
        meeting_date=_meeting_date(inputs.meeting).isoformat(),
        account_name=inputs.account.name,
        attendees=attendees or "(none recorded)",
        evidence=evidence_text,
        style_profile=DEFAULT_STYLE_PROFILE,
        section_keys=", ".join(k.value for k in LLM_SECTION_KEYS),
    )


def _meeting_date(meeting: Meeting) -> date:
    return meeting.scheduled_at.date()


# ---- post-processing -----------------------------------------------------------------


def _citation(ref: EvidenceRef) -> Citation:
    return Citation(
        source_type=ref.source_type,
        meeting_id=ref.meeting_id,
        meeting_date=ref.meeting_date,
        label=ref.label,
        quote=ref.quote,
        memory_id=ref.memory_id,
    )


def _is_citable(citation: Citation) -> bool:
    return bool(citation.meeting_id and citation.meeting_date and citation.quote)


def _map_draft(
    draft: BriefDraft,
    table: EvidenceTable,
    *,
    mode: BriefMode,
    known_contact_ids: set[str],
) -> tuple[dict[SectionKey, list[BriefItem]], set[str]]:
    """Draft -> items with citations. Returns (items per section, covered commitment ids)."""
    sections: dict[SectionKey, list[BriefItem]] = {}
    covered: set[str] = set()
    for key in LLM_SECTION_KEYS:
        for n, draft_item in enumerate(draft.sections.get(key, []), start=1):
            refs: list[EvidenceRef] = []
            for evidence_id in draft_item.evidence_ids:
                ref = table.get(evidence_id) if mode == "memory" else None
                if ref is not None and ref not in refs:
                    refs.append(ref)
            citations = [c for c in (_citation(r) for r in refs) if _is_citable(c)]
            if mode == "memory":
                if not citations:
                    logger.info("brief.item_dropped section=%s reason=no_citation", key.value)
                    continue
            else:
                citations = []
            severity = draft_item.severity
            if any(r.overdue for r in refs):
                severity = Severity.critical
            elif key in _WARNING_FLOOR and severity == Severity.info:
                severity = Severity.warning
            covered.update(r.commitment_id for r in refs if r.commitment_id)
            sections.setdefault(key, []).append(
                BriefItem(
                    id=f"{key.value}-{n}",
                    text=draft_item.text,
                    severity=severity,
                    contact_ids=[c for c in draft_item.contact_ids if c in known_contact_ids],
                    citations=citations,
                )
            )
    return sections, covered


def _overdue_item(
    commitment: Commitment, info: MeetingInfo, known_contact_ids: set[str]
) -> BriefItem:
    due = f", due {format_date(commitment.due_date)}" if commitment.due_date else ""
    # An empty source_quote falls back to the commitment's own text.
    quote = truncate(commitment.source_quote, QUOTE_MAX_CHARS) or truncate(
        commitment.text, QUOTE_MAX_CHARS
    )
    return BriefItem(
        id=f"{SectionKey.open_commitments.value}-overdue-{commitment.id}",
        text=f"Overdue: {truncate(commitment.text, 120)}{due}.",
        severity=Severity.critical,
        contact_ids=[commitment.contact_id]
        if commitment.contact_id and commitment.contact_id in known_contact_ids
        else [],
        citations=[
            Citation(
                source_type=SourceType.ledger,
                meeting_id=info.id,
                meeting_date=info.date,
                label=f"Ledger, {call_label(info.date)}",
                quote=quote,
                memory_id=None,
            )
        ],
    )


def _attendee_items(inputs: BriefInputs, *, mode: BriefMode) -> list[BriefItem]:
    """The attendees section, built in code (never by the LLM)."""
    this_date = _meeting_date(inputs.meeting)
    prior = sorted(
        (
            m
            for m in inputs.account_meetings
            if m.id != inputs.meeting.id and m.status == "done" and _meeting_date(m) < this_date
        ),
        key=lambda m: m.scheduled_at,
        reverse=True,
    )
    items: list[BriefItem] = []
    for contact in inputs.attendees:
        if contact.account_id is None:  # our own people
            continue
        text = contact.name + (f", {contact.role}" if contact.role else "")
        citations: list[Citation] = []
        if mode == "memory":
            citation = _attendee_citation(contact, prior, inputs)
            if citation is None:
                continue  # never met: nothing to cite, so the item is dropped
            citations = [citation]
        items.append(
            BriefItem(
                id=f"{SectionKey.attendees.value}-{contact.id}",
                text=text,
                severity=Severity.info,
                contact_ids=[contact.id],
                citations=citations,
            )
        )
    return items


def _attendee_citation(
    contact: Contact, prior: Sequence[Meeting], inputs: BriefInputs
) -> Citation | None:
    for meeting in prior:  # most recent first
        if contact.id not in inputs.attendee_ids_by_meeting.get(meeting.id, set()):
            continue
        meeting_date = _meeting_date(meeting)
        quote = first_line_spoken_by(meeting.transcript, [contact.name, *contact.aliases])
        if quote is None:
            return None  # a quote must be real transcript text, never synthesized
        return Citation(
            source_type=SourceType.meeting,
            meeting_id=meeting.id,
            meeting_date=meeting_date,
            label=f"{meeting.title} on {format_date(meeting_date)}",
            quote=truncate(quote, QUOTE_MAX_CHARS),
            memory_id=None,
        )
    return None


def assemble_brief(
    draft: BriefDraft,
    table: EvidenceTable,
    *,
    mode: BriefMode,
    inputs: BriefInputs,
    meetings: dict[str, MeetingInfo],
    brief_id: str,
    generated_at: datetime,
) -> Brief:
    known = {c.id for c in inputs.attendees}
    sections, covered = _map_draft(draft, table, mode=mode, known_contact_ids=known)

    if mode == "memory":
        for commitment in sorted(inputs.open_commitments, key=lambda c: c.due_date or date.max):
            overdue = commitment.due_date is not None and commitment.due_date < today()
            info = meetings.get(commitment.meeting_id)
            if overdue and commitment.id not in covered and info is not None:
                sections.setdefault(SectionKey.open_commitments, []).append(
                    _overdue_item(commitment, info, known)
                )

    attendee_items = _attendee_items(inputs, mode=mode)
    if attendee_items:
        sections[SectionKey.attendees] = attendee_items

    ordered = [
        BriefSection(key=key, title=SECTION_TITLES[key], items=sections[key])
        for key in DEFAULT_SECTION_ORDER
        if sections.get(key)
    ]
    cited = {
        (c.source_type, c.meeting_id, c.memory_id, c.quote)
        for section in ordered
        for item in section.items
        for c in item.citations
    }
    return Brief(
        id=brief_id,
        meeting_id=inputs.meeting.id,
        mode=mode,
        generated_at=generated_at,
        sections=ordered,
        facts_used=len(cited),
        preferences_applied=[],
    )


# ---- entry points --------------------------------------------------------------------


async def generate_brief(
    meeting_id: str,
    mode: BriefMode,
    *,
    llm: LLMClient,
    memory: MemoryService,
    session_factory: SessionFactory,
) -> Brief:
    """Generate, persist (upsert per meeting and mode) and return a brief."""
    if mode not in ("memory", "no_memory"):
        raise ValidationError(f"Unknown brief mode {mode!r}.")
    started = time.monotonic()
    with_memory = mode == "memory"

    inputs = load_brief_inputs(session_factory, meeting_id, include_ledger=with_memory)
    persona = load_persona()
    meetings = {
        m.id: MeetingInfo(id=m.id, title=m.title, date=_meeting_date(m))
        for m in inputs.account_meetings
    }

    table = EvidenceTable([])
    if with_memory:
        context = await _gather_memory(inputs, memory, today())
        gathered_at = time.monotonic()
        done = [
            m for m in inputs.account_meetings if m.status == "done" and m.id != inputs.meeting.id
        ]
        latest = max(done, key=lambda m: m.scheduled_at, default=None)
        table = build_evidence(
            mental_model=context.mental_model,
            latest_done_meeting=meetings[latest.id] if latest else None,
            recall_hits=context.recall_hits,
            objections=context.objections,
            commitments=inputs.open_commitments,
            meetings=meetings,
            today=today(),
        )
        logger.info(
            "brief.gathered meeting=%s evidence=%d duration_ms=%d",
            meeting_id,
            len(table.refs),
            int((gathered_at - started) * 1000),
        )

    prompt = render_brief_prompt(persona=persona, inputs=inputs, evidence_text=table.render())
    llm_started = time.monotonic()
    draft = await llm.complete_json(prompt, BriefDraft, temperature=BRIEF_TEMPERATURE)
    logger.info(
        "brief.llm meeting=%s mode=%s duration_ms=%d",
        meeting_id,
        mode,
        int((time.monotonic() - llm_started) * 1000),
    )

    brief_id, generated_at = new_brief_stamp(session_factory, meeting_id, mode)
    brief = assemble_brief(
        draft,
        table,
        mode=mode,
        inputs=inputs,
        meetings=meetings,
        brief_id=brief_id,
        generated_at=generated_at,
    )
    save_brief(session_factory, brief)
    logger.info(
        "brief.done meeting=%s mode=%s items=%d duration_ms=%d",
        meeting_id,
        mode,
        sum(len(s.items) for s in brief.sections),
        int((time.monotonic() - started) * 1000),
    )
    return brief


async def get_cached_brief(
    meeting_id: str, mode: BriefMode, *, session_factory: SessionFactory
) -> Brief | None:
    """The stored brief, or None if there is none or the account ingested a meeting since."""
    return get_fresh_brief(session_factory, meeting_id, mode)
