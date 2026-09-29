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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

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
from app.db.models import AskAnswer, Commitment, Contact, Meeting
from app.llm.client import LLMClient, get_llm_client
from app.llm.prompt_loader import render_prompt
from app.memory.memory_service import MemoryService, MentalModelText, _relationship_model_id
from app.memory.tags import account_tag, contact_tag
from app.schemas.ask import AskResponse
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
from app.schemas.enums import FactKind, Owner
from app.schemas.memory import MemoryHit
from app.schemas.reasoning import GapReport, PatternReport
from app.schemas.reflect import parse_reflect_result
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
from app.services.preferences import (
    DEFAULT_SECTION_ORDER,
    SECTION_TITLES,
    current_style,
    prompt_style_string,
)

logger = logging.getLogger(__name__)
timing_logger = logging.getLogger("uvicorn.error")

BriefMode = Literal["memory", "no_memory"]

# P3 is the biggest call in the app (a spike measured ~17-23 s at 43 evidence items), so it
# gets its own client timeout; the app default (30 s) is unchanged elsewhere. If it is
# exceeded the client raises `llm_timeout` and the brief fails: no retries of ours.
BRIEF_LLM_TIMEOUT_SECONDS = 120
BRIEF_TEMPERATURE = 0.3

# P3 style placeholder when nothing has been learned; otherwise `prompt_style_string`.
DEFAULT_STYLE_PROFILE = "default"

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
    competitors: list[str] = field(default_factory=list)
    security_keywords: list[str] = field(default_factory=list)


def _competitor_names(raw: Any) -> list[str]:
    """`competitor` in company.json: a string, an object with `name`, or a list of either."""
    items = raw if isinstance(raw, list) else [raw]
    names: list[str] = []
    for entry in items:
        name = entry.get("name") if isinstance(entry, dict) else entry
        if isinstance(name, str) and name.strip() and name.strip() not in names:
            names.append(name.strip())
    return names


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
    return Persona(
        user_name=data["ae"]["name"],
        our_company=data["vendor"]["name"],
        competitors=_competitor_names(data.get("competitor")),
        security_keywords=[
            word.strip()
            for word in data.get("security_keywords", [])
            if isinstance(word, str) and word.strip()
        ],
    )


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
    recall_sections: list[list[MemoryHit]] = field(default_factory=list)  # rank order each
    objection_hits: list[MemoryHit] = field(default_factory=list)
    cross_deal_hits: list[MemoryHit] = field(default_factory=list)
    cross_contact_alerts: list[BriefItem] = field(default_factory=list)
    deal_snapshot: list[tuple[str, MemoryHit]] = field(default_factory=list)


TOP_HITS_PER_QUERY = 3
CANDIDATES_PER_QUERY = 5

# Generic wording only: no fixture names, so the same queries work for any account.
PERSONAL_QUERY = "personal life: family, children, hobbies, travel, milestones, non-work interests"
COMPETITOR_QUERY = (
    "competitors or alternative vendors the customer has evaluated or is comparing us against"
)


WATCH_OUT_CANDIDATES = 8


def competitor_query(names: Sequence[str]) -> str:
    """The generic competitor wording, plus ' such as <names>' when the persona lists any."""
    return f"{COMPETITOR_QUERY} such as {', '.join(names)}" if names else COMPETITOR_QUERY


class Timings:
    """Per-stage durations in ms. Concurrent branches record the slowest branch (`record_max`)."""

    def __init__(self) -> None:
        self.ms: dict[str, int] = {}

    def record_max(self, name: str, seconds: float) -> None:
        self.ms[name] = max(self.ms.get(name, 0), int(seconds * 1000))

    def set(self, name: str, seconds: float) -> None:
        self.ms[name] = int(seconds * 1000)


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
    candidates: int = CANDIDATES_PER_QUERY,
    timings: Timings | None = None,
) -> list[MemoryHit]:
    """Labelled recall; if it returns nothing, ONE retry without `fact_kind` (the extraction
    model does not always label facts). Top hits are then resolved to meetings.
    """
    recall_started = time.monotonic()
    hits = await memory.recall_facts(query=query, tags=tags, fact_kind=fact_kind)
    fell_back = False
    if not hits:
        fell_back = True
        hits = await memory.recall_facts(query=query, tags=tags)
    if timings is not None:
        timings.record_max("recall", time.monotonic() - recall_started)
    # The top `candidates` by rank are resolved; the first TOP_HITS_PER_QUERY that resolve to a
    # dated meeting are kept, so unresolvable hits do not leave the section empty.
    pool = top_distinct_hits(hits, candidates)
    resolve_started = time.monotonic()
    resolved = await memory.resolve_sources(pool)
    if timings is not None:
        timings.record_max("resolve", time.monotonic() - resolve_started)
    kept = [h for h in resolved if h.meeting_id is not None and h.meeting_date is not None][
        :TOP_HITS_PER_QUERY
    ]
    logger.debug(
        "brief.recall section=%s returned=%d candidates=%d kept=%d fallback=%s",
        section,
        len(hits),
        len(pool),
        len(kept),
        fell_back,
    )
    return kept


async def _objection_evidence(
    memory: MemoryService,
    *,
    account_id: str,
    account_name: str,
    today_: date,
    timings: Timings | None = None,
) -> list[tuple[Objection, MemoryHit]]:
    query = render_prompt("reflect_objections", today=today_.isoformat(), account_name=account_name)
    reflect_started = time.monotonic()
    result = await memory.reflect_structured(
        query=query, tags=[account_tag(account_id)], schema=ObjectionReport
    )
    if timings is not None:
        timings.record_max("reflect", time.monotonic() - reflect_started)
    report = parse_reflect_result("R1", result, ObjectionReport)
    if not isinstance(report, ObjectionReport):
        return []
    resolve_started = time.monotonic()
    sources = await memory.resolve_sources(result.sources)
    if timings is not None:
        timings.record_max("resolve", time.monotonic() - resolve_started)
    return match_objection_sources(report, sources)


def _name_in_text(name: str, text: str) -> bool:
    return name.casefold() in text.casefold()


def _has_name_token(name: str, text: str) -> bool:
    tokens = {token.strip(".,;:'\"()[]{}").casefold() for token in name.split()}
    words = {token.strip(".,;:'\"()[]{}").casefold() for token in text.split()}
    return bool(tokens & words)


def _has_concern_token(concern: str, text: str) -> bool:
    tokens = set(re.findall(r"[a-z0-9]{3,}", concern.casefold()))
    words = set(re.findall(r"[a-z0-9]{3,}", text.casefold()))
    return bool(tokens & words)


def _meeting_label(meeting: Meeting | MeetingInfo | None, meeting_date: date) -> str:
    title = meeting.title if meeting is not None else "Meeting"
    return f"{title} · {meeting_date:%b} {meeting_date.day}"


def _security_hit(text: str, keywords: Sequence[str]) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "", text.casefold())
    return any(re.sub(r"[^a-z0-9]+", "", word.casefold()) in normalized for word in keywords)


def _security_concern_hit(text: str, keywords: Sequence[str]) -> bool:
    return _security_hit(text, keywords) and bool(
        re.search(
            r"\b(raised?|concern|require[sd]?|must(?:-have)?|blocker|mandatory|insist(?:ed)?|need(?:s|ed)?)\b",
            text,
            re.I,
        )
    )


def _contact_mentioned(text: str, contacts: Sequence[Contact]) -> Contact | None:
    lowered = text.casefold()
    return next(
        (
            contact
            for contact in contacts
            if contact.account_id is not None
            and any(
                name and name.casefold() in lowered for name in [contact.name, *contact.aliases]
            )
        ),
        None,
    )


def _b5_alerts(
    inputs: BriefInputs,
    security_hits: Sequence[MemoryHit],
    absence_hits: Sequence[MemoryHit],
    keywords: Sequence[str],
) -> list[BriefItem]:
    meetings = {meeting.id: meeting for meeting in inputs.all_meetings}
    upcoming = [contact for contact in inputs.attendees if contact.account_id is not None]
    grouped: dict[str, list[MemoryHit]] = {}
    for hit in security_hits:
        if (
            hit.meeting_id
            and hit.meeting_date
            and hit.meeting_id in meetings
            and _security_concern_hit(hit.text, keywords)
        ):
            grouped.setdefault(hit.meeting_id, []).append(hit)

    output: list[BriefItem] = []
    for meeting_id, hits in grouped.items():
        call_attendees = inputs.attendee_ids_by_meeting.get(meeting_id, set())
        absent = [contact for contact in upcoming if contact.id not in call_attendees]
        if not absent:
            continue
        raised = next(
            (
                (hit, raiser)
                for hit in hits
                if (raiser := _contact_mentioned(hit.text, inputs.account_contacts)) is not None
            ),
            None,
        )
        if raised is None or raised[1] is None:
            continue
        source_hit, raiser = raised
        assert source_hit.meeting_date is not None
        citations = [
            Citation(
                source_type=SourceType.meeting,
                meeting_id=meeting_id,
                meeting_date=source_hit.meeting_date,
                label=_meeting_label(meetings[meeting_id], source_hit.meeting_date),
                quote=truncate(source_hit.text, QUOTE_MAX_CHARS),
                memory_id=source_hit.memory_id,
            )
        ]
        absent_names = {contact.name.split()[0].casefold() for contact in absent}
        for hit in absence_hits:
            if (
                hit.meeting_id
                and hit.meeting_id != meeting_id
                and hit.meeting_date
                and any(name in hit.text.casefold() for name in absent_names)
                and "security" in hit.text.casefold()
                and re.search(r"has(?:n't| not) been in", hit.text, re.IGNORECASE)
            ):
                source_meeting = meetings.get(hit.meeting_id)
                if source_meeting is not None:
                    citations.append(
                        Citation(
                            source_type=SourceType.meeting,
                            meeting_id=hit.meeting_id,
                            meeting_date=hit.meeting_date,
                            label=_meeting_label(source_meeting, hit.meeting_date),
                            quote=truncate(hit.text, QUOTE_MAX_CHARS),
                            memory_id=hit.memory_id,
                        )
                    )
                    break
        names = ", ".join(contact.name for contact in absent)
        topics = [
            keyword
            for keyword in keywords
            if keyword.casefold() != "security" and _security_hit(source_hit.text, [keyword])
        ]
        topic_text = " and ".join(topics) or "security"
        output.append(
            BriefItem(
                id=f"b5-{meeting_id}-{source_hit.memory_id}",
                text=(
                    f"{raiser.name} raised a {topic_text} concern on "
                    f"{format_date(source_hit.meeting_date)}; {names} was not on that call."
                ),
                severity=Severity.warning,
                contact_ids=[contact.id for contact in absent],
                citations=citations,
            )
        )
    return output


async def _recall_objection_hits(
    memory: MemoryService, account_id: str, timings: Timings
) -> list[MemoryHit]:
    started = time.monotonic()
    hits = await memory.recall_facts(
        query="unresolved objection blocker concern requirement must-have not yet resolved",
        tags=[account_tag(account_id)],
        fact_kind=FactKind.objection,
    )
    timings.record_max("recall", time.monotonic() - started)
    return [hit for hit in hits if hit.meeting_id and hit.meeting_date][:5]


async def _cross_deal_recall(
    memory: MemoryService,
    *,
    current_account_id: str,
    other_accounts: Sequence[Any],
    objections: Sequence[MemoryHit],
    timings: Timings,
) -> list[MemoryHit]:
    work = [(topic, account) for topic in objections for account in other_accounts]
    if not work:
        return []

    async def recall(topic: MemoryHit, account: Any) -> list[MemoryHit]:
        started = time.monotonic()
        hits = await memory.recall_facts(
            query=f"{topic.text} resolved resolution worked trust portal pen-test",
            tags=[account_tag(account.id)],
        )
        timings.record_max("recall", time.monotonic() - started)
        return [
            hit
            for hit in hits[:3]
            if hit.meeting_id
            and hit.meeting_date
            and account_tag(account.id) in hit.tags
            and account_tag(current_account_id) not in hit.tags
        ]

    groups = await asyncio.gather(*(recall(topic, account) for topic, account in work))
    dedup: dict[str, MemoryHit] = {}
    for group in groups:
        for hit in group:
            dedup.setdefault(hit.memory_id, hit)
    return list(dedup.values())


def _deal_snapshot_parts(
    *,
    budget_hits: Sequence[MemoryHit],
    decision_hits: Sequence[MemoryHit],
    competitor_hits: Sequence[MemoryHit],
    competitors: Sequence[str],
    deal_value_usd: int | None,
) -> list[tuple[str, MemoryHit]]:
    parts: list[tuple[str, MemoryHit]] = []
    budget = max(
        (
            hit
            for hit in budget_hits
            if hit.meeting_id and hit.meeting_date and re.search(r"budget|\$|usd", hit.text, re.I)
        ),
        key=lambda hit: hit.meeting_date or date.min,
        default=None,
    )
    if budget and deal_value_usd is not None:
        amount = (
            f"${deal_value_usd / 1000:g}K" if deal_value_usd % 1000 == 0 else f"${deal_value_usd:,}"
        )
        parts.append((f"Budget about {amount}", budget))

    decision = max(
        (
            hit
            for hit in decision_hits
            if hit.meeting_id and hit.meeting_date and re.search(r"decision|decide", hit.text, re.I)
        ),
        key=lambda hit: hit.meeting_date or date.min,
        default=None,
    )
    if decision:
        date_match = re.search(
            r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:,?\s+\d{4})?",
            decision.text,
            re.I,
        )
        if date_match:
            value = date_match.group(0)
            parsed_date = next(
                (
                    parsed
                    for pattern in (
                        "%B %d, %Y",
                        "%B %d %Y",
                        "%b %d, %Y",
                        "%b %d %Y",
                        "%B %d",
                        "%b %d",
                    )
                    if (parsed := _try_parse_snapshot_date(value, pattern)) is not None
                ),
                None,
            )
            decision_label = (
                f"{parsed_date:%b} {parsed_date.day}, {parsed_date.year}" if parsed_date else value
            )
            parts.append((f"Decision by {decision_label}", decision))

    competitor = next(
        (
            (name, hit)
            for name in competitors
            for hit in competitor_hits
            if hit.meeting_id and hit.meeting_date and name.casefold() in hit.text.casefold()
        ),
        None,
    )
    if competitor:
        parts.append((f"{competitor[0]} evaluated", competitor[1]))
    return parts


def _try_parse_snapshot_date(value: str, pattern: str) -> date | None:
    try:
        parsed = datetime.strptime(value, pattern).date()
    except ValueError:
        return None
    return parsed.replace(year=2026) if "%Y" not in pattern else parsed


def _cross_contact_item(
    gap: Any,
    attendees: Sequence[Contact],
    sources: Sequence[MemoryHit],
    meetings: Sequence[Meeting],
) -> BriefItem | None:
    absent = [
        contact
        for contact in attendees
        if any(
            _name_in_text(contact.name, name)
            or any(_name_in_text(alias, name) for alias in contact.aliases)
            for name in gap.not_heard_by
        )
    ]
    if not absent:
        return None
    by_meeting = {
        hit.meeting_id: hit
        for hit in sources
        if hit.meeting_id is not None and hit.meeting_date is not None
    }
    meeting_by_id = {meeting.id: meeting for meeting in meetings}

    def quote_from(hit: MemoryHit, predicate: Any) -> str | None:
        meeting = meeting_by_id.get(hit.meeting_id or "")
        if meeting is None or not meeting.transcript:
            return None
        for raw in meeting.transcript.splitlines():
            match = _LINE.match(raw.strip())
            if match and predicate(match.group("speaker"), match.group("text")):
                return match.group("text").strip()
        return None

    def raised_quote(speaker: str, quote: str) -> bool:
        return _has_name_token(gap.raised_by, speaker) and _has_concern_token(gap.concern, quote)

    raised = next((hit for hit in by_meeting.values() if quote_from(hit, raised_quote)), None)
    if raised is None or gap.answered_on is None:
        return None
    absent_hit = next(
        (
            hit
            for hit in by_meeting.values()
            if hit.meeting_id != raised.meeting_id
            and quote_from(
                hit,
                lambda _speaker, quote: (
                    any(_name_in_text(contact.name.split()[0], quote) for contact in absent)
                    and "security" in quote.casefold()
                    and any(
                        phrase in quote.casefold()
                        for phrase in ("hasn't been in", "has not been in", "not been in")
                    )
                ),
            )
        ),
        None,
    )
    if absent_hit is None:
        return None
    cited = [raised, absent_hit]
    quotes = {
        raised.memory_id: quote_from(raised, raised_quote),
        absent_hit.memory_id: quote_from(
            absent_hit,
            lambda _speaker, quote: (
                any(_name_in_text(contact.name.split()[0], quote) for contact in absent)
                and "security" in quote.casefold()
                and any(
                    phrase in quote.casefold()
                    for phrase in ("hasn't been in", "has not been in", "not been in")
                )
            ),
        ),
    }
    citations = [
        Citation(
            source_type=SourceType.meeting,
            meeting_id=hit.meeting_id,
            meeting_date=hit.meeting_date,
            label=_meeting_label(meeting_by_id.get(hit.meeting_id or ""), hit.meeting_date),
            quote=truncate(quotes.get(hit.memory_id) or hit.text, QUOTE_MAX_CHARS),
            memory_id=hit.memory_id,
        )
        for hit in cited
        if hit.meeting_id is not None and hit.meeting_date is not None
    ]
    names = ", ".join(contact.name for contact in absent)
    return BriefItem(
        id=f"cross_contact-{raised.memory_id}-{absent_hit.memory_id}",
        text=(
            f"{gap.raised_by}'s {gap.concern} concern was answered, but {names} "
            "was not present when it was raised or answered."
        ),
        severity=Severity.warning,
        contact_ids=[contact.id for contact in absent],
        citations=citations,
    )


async def _cross_contact_alerts(
    memory: MemoryService,
    *,
    account_id: str,
    account_name: str,
    attendees: Sequence[Contact],
    meetings: Sequence[Meeting],
    timings: Timings | None = None,
) -> list[BriefItem]:
    attendee_text = "; ".join(
        f"{contact.name} ({contact.role})" if contact.role else contact.name
        for contact in attendees
    )
    query = render_prompt(
        "reflect_cross_contact",
        today=today().isoformat(),
        account_name=account_name,
        attendees=attendee_text or "(none recorded)",
    )
    started = time.monotonic()
    result = await memory.reflect_structured(
        query=query, tags=[account_tag(account_id)], schema=GapReport, budget="mid"
    )
    if timings is not None:
        timings.record_max("reflect", time.monotonic() - started)
    report = parse_reflect_result("R3", result, GapReport)
    if not isinstance(report, GapReport) or not report.gaps:
        return []
    resolve_started = time.monotonic()
    sources = await memory.resolve_sources(result.sources)
    if timings is not None:
        timings.record_max("resolve", time.monotonic() - resolve_started)
    return [
        item
        for gap in report.gaps
        if (item := _cross_contact_item(gap, attendees, sources, meetings)) is not None
    ]


def _overlap_count(left: str, right: str) -> int:
    left_tokens = set(re.findall(r"[a-z0-9]{3,}", left.casefold()))
    right_tokens = set(re.findall(r"[a-z0-9]{3,}", right.casefold()))
    return len(left_tokens & right_tokens)


def _pattern_item(
    pattern: Any,
    current_account_id: str,
    sources: Sequence[MemoryHit],
    meetings: Sequence[MeetingInfo] = (),
) -> BriefItem | None:
    current_tag = account_tag(current_account_id)
    named_account_tokens = set(re.findall(r"[a-z0-9]{3,}", pattern.other_account.casefold()))
    other_sources: list[tuple[str, MemoryHit]] = []
    for source in sources:
        source_accounts = [tag for tag in source.tags if tag.startswith("account:")]
        if (
            source.meeting_id is not None
            and source.meeting_date is not None
            and len(source_accounts) == 1
            and source_accounts[0] != current_tag
            and bool(
                named_account_tokens
                & set(re.findall(r"[a-z0-9]{3,}", source_accounts[0].casefold()))
            )
        ):
            other_sources.append((source_accounts[0], source))

    objection_source = next(
        (
            (account, source)
            for account, source in other_sources
            if _overlap_count(pattern.objection, source.text) >= 1
        ),
        None,
    )
    if objection_source is None:
        return None
    account_id, objection_hit = objection_source
    resolved_hit = next(
        (
            source
            for source_account, source in other_sources
            if source_account == account_id
            and source.meeting_id != objection_hit.meeting_id
            and _overlap_count(pattern.what_worked, source.text) >= 2
        ),
        None,
    )
    if resolved_hit is None:
        return None

    meeting_by_id = {meeting.id: meeting for meeting in meetings}
    citations = [
        Citation(
            source_type=SourceType.meeting,
            meeting_id=source.meeting_id,
            meeting_date=source.meeting_date,
            label=_meeting_label(meeting_by_id.get(source.meeting_id), source.meeting_date),
            quote=truncate(source.text, QUOTE_MAX_CHARS),
            memory_id=source.memory_id,
        )
        for source in (objection_hit, resolved_hit)
        if source.meeting_id is not None and source.meeting_date is not None
    ]
    return BriefItem(
        id=f"cross_deal-{objection_hit.memory_id}-{resolved_hit.memory_id}",
        text=(
            f"{pattern.objection} was resolved at {pattern.other_account} with "
            f"{pattern.what_worked}."
        ),
        severity=Severity.warning,
        contact_ids=[],
        citations=citations,
    )


async def _cross_deal_patterns(
    memory: MemoryService,
    *,
    account_id: str,
    deal_stage: str,
    meetings: Sequence[MeetingInfo] = (),
    timings: Timings | None = None,
) -> list[BriefItem]:
    recall_started = time.monotonic()
    current_hits = await memory.recall_facts(
        query="Current objections, security blockers and must-have requirements",
        tags=[account_tag(account_id)],
    )
    if timings is not None:
        timings.record_max("recall", time.monotonic() - recall_started)
    current_objections = "\n".join(hit.text for hit in current_hits[:8]) or "(none recalled)"
    query = render_prompt(
        "reflect_patterns", deal_stage=deal_stage, current_objections=current_objections
    )
    reflect_started = time.monotonic()
    result = await memory.reflect_structured(
        query=query, tags=[], schema=PatternReport, budget="high"
    )
    if timings is not None:
        timings.record_max("reflect", time.monotonic() - reflect_started)
    report = parse_reflect_result("R4", result, PatternReport)
    if not isinstance(report, PatternReport) or not report.patterns:
        return []
    resolve_started = time.monotonic()
    sources = await memory.resolve_sources(result.sources)
    if timings is not None:
        timings.record_max("resolve", time.monotonic() - resolve_started)
    return [
        item
        for pattern in report.patterns
        if (item := _pattern_item(pattern, account_id, sources, meetings)) is not None
    ]


async def _timed_mental_model(
    memory: MemoryService, name: str, timings: Timings
) -> MentalModelText | None:
    started = time.monotonic()
    try:
        return await memory.get_mental_model(name)
    finally:
        timings.record_max("mental_model", time.monotonic() - started)


async def _gather_memory(
    inputs: BriefInputs,
    memory: MemoryService,
    today_: date,
    competitors: Sequence[str] = (),
    security_keywords: Sequence[str] = (),
    timings: Timings | None = None,
) -> MemoryContext:
    account = inputs.account
    external = [c for c in inputs.attendees if c.account_id is not None]
    timings = timings or Timings()

    async def recall(
        query: str, tags: Sequence[str], kind: FactKind | None = None
    ) -> list[MemoryHit]:
        started = time.monotonic()
        hits = await memory.recall_facts(query=query, tags=tags, fact_kind=kind)
        timings.record_max("recall", time.monotonic() - started)
        return [hit for hit in hits if hit.meeting_id and hit.meeting_date]

    gather_started = time.monotonic()
    results = await asyncio.gather(
        _timed_mental_model(memory, _relationship_model_id(account.id), timings),
        _recall_top(
            memory,
            section="watch_outs",
            query=competitor_query(competitors),
            tags=[account_tag(account.id)],
            fact_kind=FactKind.competitor,
            candidates=WATCH_OUT_CANDIDATES,
            timings=timings,
        ),
        recall(
            "unresolved objection blocker concern requirement must-have not yet resolved",
            [account_tag(account.id)],
            FactKind.objection,
        ),
        recall(" ".join(security_keywords), [account_tag(account.id)]),
        recall("hasn't been in the security conversations", [account_tag(account.id)]),
        recall(
            "account budget approved amount deal value pilot budget",
            [account_tag(account.id)],
            FactKind.deal_fact,
        ),
        recall(
            "decision date by which decision must be made",
            [account_tag(account.id)],
            FactKind.deal_fact,
        ),
        *(
            _recall_top(
                memory,
                section=f"personal_touchpoints:{c.id}",
                query=f"{c.name} {PERSONAL_QUERY}",
                tags=[contact_tag(c.id)],
                fact_kind=FactKind.personal,
                timings=timings,
            )
            for c in external
        ),
        return_exceptions=True,
    )
    labels = [
        "mental_model",
        "watch_outs",
        "unresolved_objections",
        "security_gaps",
        "security_absence",
        "budget_snapshot",
        "decision_snapshot",
    ]
    labels += [f"personal_touchpoints:{c.id}" for c in external]

    failed = 0
    for label, result in zip(labels, results, strict=True):
        if isinstance(result, MemoryUnavailableError):
            failed += 1
            logger.warning("brief.section_degraded section=%s error=%s", label, result.message)
        elif isinstance(result, BaseException):
            raise result  # a bug or a non-memory error must not be swallowed

    (
        mental_model,
        competitor_hits,
        objections,
        security_hits,
        absence_hits,
        budget_hits,
        decision_hits,
        *personal_recalls,
    ) = results
    context = MemoryContext()
    if isinstance(mental_model, MentalModelText):
        context.mental_model = mental_model
    if isinstance(objections, list):
        context.objection_hits = [hit for hit in objections if isinstance(hit, MemoryHit)][:5]
    if isinstance(security_hits, list) and isinstance(absence_hits, list):
        context.cross_contact_alerts = _b5_alerts(
            inputs, security_hits, absence_hits, security_keywords
        )
    if isinstance(competitor_hits, list):
        context.recall_sections.append(
            [hit for hit in competitor_hits if isinstance(hit, MemoryHit)]
        )
    for personal_recall in personal_recalls:
        if isinstance(personal_recall, list):
            context.recall_sections.append(
                [hit for hit in personal_recall if isinstance(hit, MemoryHit)]
            )
    try:
        context.cross_deal_hits = await _cross_deal_recall(
            memory,
            current_account_id=account.id,
            other_accounts=inputs.other_accounts,
            objections=context.objection_hits,
            timings=timings,
        )
    except MemoryUnavailableError as exc:
        failed += 1
        logger.warning("brief.section_degraded section=cross_deal error=%s", exc.message)
    context.deal_snapshot = _deal_snapshot_parts(
        budget_hits=budget_hits if isinstance(budget_hits, list) else [],
        decision_hits=decision_hits if isinstance(decision_hits, list) else [],
        competitor_hits=context.recall_sections[0] if context.recall_sections else [],
        competitors=competitors,
        deal_value_usd=account.deal_value_usd,
    )
    if context.deal_snapshot:
        context.recall_sections.append([hit for _, hit in context.deal_snapshot])
    timings.set("gather", time.monotonic() - gather_started)
    if failed >= len(results):
        raise MemoryUnavailableError("Every memory call for the brief failed.")
    return context


# ---- prompt ------------------------------------------------------------------------


def render_brief_prompt(
    *,
    persona: Persona,
    inputs: BriefInputs,
    evidence_text: str,
    style_profile: str = DEFAULT_STYLE_PROFILE,
) -> str:
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
        style_profile=style_profile,
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


# (customer-owned?, due date, commitment id): sorts us-owned first, then most overdue, then id.
_OverdueRank = tuple[bool, date, str]

MAX_CRITICAL_ITEMS = 1


def _rank_of(ref: EvidenceRef) -> _OverdueRank:
    assert ref.due_date is not None and ref.commitment_id is not None
    return (ref.owner != Owner.us.value, ref.due_date, ref.commitment_id)


def _apply_severity_cap(
    sections: dict[SectionKey, list[BriefItem]], overdue_of: dict[str, list[_OverdueRank]]
) -> None:
    """Keep the oldest us-owned overdue commitment red and consolidate the rest.

    Critical candidates are ONLY open_commitments items citing an overdue ledger row owned by
    us, ranked most days overdue first, then commitment id; the top ones stay critical. A
    customer-owned row is never critical. Everything else that would be critical (other overdue
    rows, customer-owned rows, any agenda/alerts/other-section item citing or restating overdue
    rows, an LLM `critical` anywhere) becomes `warning`. open_commitments is then ordered by
    severity, then rank (us-owned overdue first, most overdue first).
    """
    commitments = sections.get(SectionKey.open_commitments, [])
    candidates = sorted(
        (i for i in commitments if i.id in overdue_of), key=lambda i: min(overdue_of[i.id])
    )
    us_candidates = sorted(
        (i for i in commitments if any(not r[0] for r in overdue_of.get(i.id, []))),
        key=lambda i: min(r for r in overdue_of[i.id] if not r[0]),
    )
    critical_ids = {i.id for i in us_candidates[:MAX_CRITICAL_ITEMS]}
    grouped = [i for i in us_candidates[MAX_CRITICAL_ITEMS:]]
    if grouped:
        group_ids = {i.id for i in grouped}
        group_ranks = [rank for item in grouped for rank in overdue_of.get(item.id, [])]
        group_citations = list(
            {
                citation.model_dump_json(): citation
                for item in grouped
                for citation in item.citations
            }.values()
        )
        group_contacts = list(
            dict.fromkeys(contact for item in grouped for contact in item.contact_ids)
        )
        details = "; ".join(item.text.removeprefix("Overdue: ").rstrip(".") for item in grouped)
        group_item = BriefItem(
            id="open_commitments-also-overdue",
            text=f"Also overdue: {details}.",
            severity=Severity.warning,
            contact_ids=group_contacts,
            citations=group_citations,
        )
        commitments = [item for item in commitments if item.id not in group_ids]
        commitments.append(group_item)
        sections[SectionKey.open_commitments] = commitments
        overdue_of[group_item.id] = group_ranks

    sections[SectionKey.alerts] = [
        item for item in sections.get(SectionKey.alerts, []) if item.id not in overdue_of
    ]
    for items in sections.values():
        for idx, item in enumerate(items):
            if item.id in critical_ids:
                severity = Severity.critical
            elif item.id in overdue_of and all(rank[0] for rank in overdue_of[item.id]):
                severity = Severity.info
            elif item.id in overdue_of or item.severity == Severity.critical:
                severity = Severity.warning
            else:
                severity = item.severity
            items[idx] = item.model_copy(update={"severity": severity})
    if commitments:
        rank_pos = {i.id: n for n, i in enumerate(candidates)}
        order = {Severity.critical: 0, Severity.warning: 1, Severity.info: 2}
        sections[SectionKey.open_commitments] = [
            item
            for _, _, item in sorted(
                ((order[i.severity], rank_pos.get(i.id, len(candidates)), i) for i in commitments),
                key=lambda t: (t[0], t[1]),
            )
        ]


def _drop_repeated_competitor_objections(
    sections: dict[SectionKey, list[BriefItem]], competitors: Sequence[str]
) -> None:
    """Keep a competitor watch-out when an objection repeats its cited fact and meeting."""
    watch_outs = sections.get(SectionKey.watch_outs, [])
    objections = sections.get(SectionKey.unresolved_objections, [])
    if not watch_outs or not objections or not competitors:
        return

    def competitor_in(text: str) -> str | None:
        return next((name for name in competitors if name.casefold() in text.casefold()), None)

    retained: list[BriefItem] = []
    for objection in objections:
        objection_name = competitor_in(
            " ".join([objection.text, *(citation.quote or "" for citation in objection.citations)])
        )
        repeats_watch_out = objection_name is not None and any(
            competitor_in(watch.text) == objection_name
            and any(
                objection_citation.meeting_id == watch_citation.meeting_id
                for objection_citation in objection.citations
                for watch_citation in watch.citations
            )
            for watch in watch_outs
        )
        if repeats_watch_out:
            logger.info(
                "brief.item_dropped section=unresolved_objections "
                "reason=duplicate_competitor_watchout competitor=%s",
                objection_name,
            )
        else:
            retained.append(objection)
    sections[SectionKey.unresolved_objections] = retained


def _map_draft(
    draft: BriefDraft,
    table: EvidenceTable,
    *,
    mode: BriefMode,
    known_contact_ids: set[str],
) -> tuple[dict[SectionKey, list[BriefItem]], set[str], dict[str, list[_OverdueRank]]]:
    """Draft -> items with citations.

    Returns (items per section, covered commitment ids, overdue ledger rows each item cites).
    Severity is NOT forced here; `_apply_severity_cap` ranks and caps it afterwards.
    """
    sections: dict[SectionKey, list[BriefItem]] = {}
    covered: set[str] = set()
    overdue_of: dict[str, list[_OverdueRank]] = {}
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
            if key in _WARNING_FLOOR and severity == Severity.info:
                severity = Severity.warning
            if key == SectionKey.open_commitments:  # only these items 'cover' a commitment
                covered.update(r.commitment_id for r in refs if r.commitment_id)
            item_id = f"{key.value}-{n}"
            ranks = [_rank_of(r) for r in refs if r.overdue and r.due_date and r.commitment_id]
            if ranks:
                overdue_of[item_id] = ranks
            sections.setdefault(key, []).append(
                BriefItem(
                    id=item_id,
                    text=draft_item.text,
                    severity=severity,
                    contact_ids=[c for c in draft_item.contact_ids if c in known_contact_ids],
                    citations=citations,
                )
            )
    return sections, covered, overdue_of


def _filter_cross_deal_draft(
    draft: BriefDraft,
    table: EvidenceTable,
    *,
    current_account_id: str,
    account_names: Mapping[str, str],
    meeting_account_ids: Mapping[str, str],
) -> BriefDraft:
    """Permit one tightly scoped cross-account Watch-outs sentence."""
    sections: dict[SectionKey, list[Any]] = {}
    accepted = False
    names_to_ids = {name.casefold(): account_id for account_id, name in account_names.items()}
    for key, draft_items in draft.sections.items():
        kept: list[Any] = []
        for item in draft_items:
            refs = [table.get(evidence_id) for evidence_id in item.evidence_ids]
            cited = [ref for ref in refs if ref is not None]
            cross_refs = [ref for ref in cited if ref.kind == "cross_deal"]
            if key == SectionKey.watch_outs and cross_refs:
                match = re.match(r"^At\s+([^,]+),", item.text, re.IGNORECASE)
                account_id = names_to_ids.get(match.group(1).strip().casefold()) if match else None
                valid = (
                    not accepted
                    and bool(match)
                    and len(item.text.split()) <= 40
                    and len(cross_refs) == len(item.evidence_ids)
                    and account_id is not None
                    and account_id != current_account_id
                    and all(ref.account_id == account_id for ref in cross_refs)
                    and all(
                        ref.meeting_id is not None
                        and meeting_account_ids.get(ref.meeting_id) == account_id
                        for ref in cross_refs
                    )
                )
                if not valid:
                    logger.info("brief.cross_deal_item_dropped reason=invalid_citations_or_text")
                    continue
                accepted = True
            kept.append(item)
        sections[key] = kept
    return draft.model_copy(update={"sections": sections})


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
            label=_meeting_label(meeting, meeting_date),
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
    competitor_hits: Sequence[MemoryHit] = (),
    competitors: Sequence[str] = (),
    cross_contact_alerts: Sequence[BriefItem] = (),
    cross_deal_patterns: Sequence[BriefItem] = (),
    deal_snapshot: Sequence[tuple[str, MemoryHit]] = (),
) -> Brief:
    known = {c.id for c in inputs.attendees}
    account_names = {
        account.id: account.name for account in [inputs.account, *inputs.other_accounts]
    }
    draft = _filter_cross_deal_draft(
        draft,
        table,
        current_account_id=inputs.account.id,
        account_names=account_names,
        meeting_account_ids={meeting.id: meeting.account_id for meeting in inputs.all_meetings},
    )
    sections, covered, overdue_of = _map_draft(draft, table, mode=mode, known_contact_ids=known)

    if mode == "memory" and deal_snapshot:
        meeting_by_id = {meeting.id: meeting for meeting in inputs.all_meetings}
        citations = [
            Citation(
                source_type=SourceType.meeting,
                meeting_id=hit.meeting_id,
                meeting_date=hit.meeting_date,
                label=_meeting_label(meeting_by_id.get(hit.meeting_id or ""), hit.meeting_date),
                quote=truncate(hit.text, QUOTE_MAX_CHARS),
                memory_id=hit.memory_id,
            )
            for _, hit in deal_snapshot
            if hit.meeting_id and hit.meeting_date and hit.text.strip()
        ]
        parts = [
            text
            for text, hit in deal_snapshot
            if hit.meeting_id and hit.meeting_date and hit.text.strip()
        ]
        if parts and citations:
            sections.setdefault(SectionKey.where_left_off, []).insert(
                0,
                BriefItem(
                    id="where_left_off-deal-snapshot",
                    text=" · ".join(parts),
                    severity=Severity.info,
                    contact_ids=[],
                    citations=citations,
                ),
            )

    if mode == "memory" and competitors:
        competitor = next(
            (
                (name, hit)
                for name in competitors
                for hit in competitor_hits
                if name.casefold() in hit.text.casefold()
                and hit.meeting_id is not None
                and hit.meeting_date is not None
            ),
            None,
        )
        if competitor is not None:
            name, hit = competitor
            assert hit.meeting_id is not None and hit.meeting_date is not None
            # The code-built B4 item replaces model-authored versions of this same fact.
            sections[SectionKey.watch_outs] = []
            sections.setdefault(SectionKey.watch_outs, []).append(
                BriefItem(
                    id="watch_outs-competitor",
                    text=f"{inputs.account.name} has looked at {name}.",
                    severity=Severity.warning,
                    contact_ids=[],
                    citations=[
                        Citation(
                            source_type=SourceType.meeting,
                            meeting_id=hit.meeting_id,
                            meeting_date=hit.meeting_date,
                            label=_meeting_label(
                                next(
                                    (m for m in inputs.all_meetings if m.id == hit.meeting_id), None
                                ),
                                hit.meeting_date,
                            ),
                            quote=truncate(hit.text, QUOTE_MAX_CHARS),
                            memory_id=hit.memory_id,
                        )
                    ],
                )
            )
        _drop_repeated_competitor_objections(sections, competitors)

    if mode == "memory" and cross_contact_alerts:
        sections.setdefault(SectionKey.alerts, []).extend(
            item
            for item in cross_contact_alerts
            if item.citations and all(_is_citable(c) for c in item.citations)
        )

    if mode == "memory" and cross_deal_patterns:
        sections.setdefault(SectionKey.watch_outs, []).extend(
            item
            for item in cross_deal_patterns
            if item.citations and all(_is_citable(c) for c in item.citations)
        )

    if mode == "memory":
        for commitment in sorted(inputs.open_commitments, key=lambda c: c.due_date or date.max):
            overdue = commitment.due_date is not None and commitment.due_date < today()
            info = meetings.get(commitment.meeting_id)
            if overdue and commitment.id not in covered and info is not None:
                forced = _overdue_item(commitment, info, known)
                overdue_of[forced.id] = [
                    (commitment.owner != Owner.us, commitment.due_date or date.max, commitment.id)
                ]
                sections.setdefault(SectionKey.open_commitments, []).append(forced)
    _apply_severity_cap(sections, overdue_of)

    attendee_items = _attendee_items(inputs, mode=mode)
    if attendee_items:
        sections[SectionKey.attendees] = attendee_items
    if mode == "memory":
        pinned = [
            item
            for ask_answer in inputs.pinned_ask_answers
            if (item := _pinned_ask_item(ask_answer)) is not None
        ]
        if pinned:
            sections[SectionKey.your_questions] = pinned

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


def _pinned_ask_item(ask_answer: AskAnswer) -> BriefItem | None:
    try:
        answer = AskResponse.model_validate({"ask_answer_id": ask_answer.id, **ask_answer.answer})
    except PydanticValidationError:
        logger.warning("brief.pinned_ask_dropped ask_id=%s reason=invalid_output", ask_answer.id)
        return None
    if not answer.grounded or not answer.citations:
        return None
    return BriefItem(
        id=f"ask-{ask_answer.id}",
        text=f"Q: {ask_answer.question}\nA: {answer.answer}",
        severity=Severity.info,
        contact_ids=[],
        citations=answer.citations,
    )


def add_pinned_ask_answer(brief: Brief, ask_answer: AskAnswer) -> Brief:
    """Append one grounded pinned answer to an existing cached memory brief."""
    item = _pinned_ask_item(ask_answer)
    if item is None:
        return brief
    sections = list(brief.sections)
    idx = next(
        (i for i, section in enumerate(sections) if section.key == SectionKey.your_questions),
        None,
    )
    if idx is None:
        sections.append(
            BriefSection(
                key=SectionKey.your_questions,
                title=SECTION_TITLES[SectionKey.your_questions],
                items=[item],
            )
        )
    else:
        existing = sections[idx]
        items = [entry for entry in existing.items if entry.id != item.id]
        sections[idx] = existing.model_copy(update={"items": [*items, item]})
    existing_facts = {
        (citation.source_type, citation.meeting_id, citation.memory_id, citation.quote)
        for section in brief.sections
        for entry in section.items
        for citation in entry.citations
    }
    new_facts = {
        (citation.source_type, citation.meeting_id, citation.memory_id, citation.quote)
        for citation in item.citations
    } - existing_facts
    return brief.model_copy(
        update={"sections": sections, "facts_used": brief.facts_used + len(new_facts)}
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
    timings = Timings()

    inputs = load_brief_inputs(session_factory, meeting_id, include_ledger=with_memory)
    persona = load_persona()
    meetings = {
        m.id: MeetingInfo(id=m.id, title=m.title, date=_meeting_date(m))
        for m in inputs.all_meetings
    }
    timings.set("load", time.monotonic() - started)

    table = EvidenceTable([])
    competitor_hits: Sequence[MemoryHit] = ()
    cross_contact_alerts: Sequence[BriefItem] = ()
    cross_deal_patterns: Sequence[BriefItem] = ()
    if with_memory:
        context = await _gather_memory(
            inputs,
            memory,
            today(),
            competitors=persona.competitors,
            security_keywords=persona.security_keywords,
            timings=timings,
        )
        gathered_at = time.monotonic()
        ingested = [
            m
            for m in inputs.account_meetings
            if m.ingested_at is not None and m.id != inputs.meeting.id
        ]
        latest = max(ingested, key=lambda m: m.scheduled_at, default=None)
        table = build_evidence(
            mental_model=context.mental_model,
            latest_ingested_meeting=meetings[latest.id] if latest else None,
            recall_sections=context.recall_sections,
            objection_hits=context.objection_hits,
            cross_deal_hits=context.cross_deal_hits,
            objections=(),
            commitments=inputs.open_commitments,
            meetings=meetings,
            today=today(),
        )
        competitor_hits = context.recall_sections[0] if context.recall_sections else []
        cross_contact_alerts = context.cross_contact_alerts
        logger.info(
            "brief.gathered meeting=%s evidence=%d duration_ms=%d",
            meeting_id,
            len(table.refs),
            int((gathered_at - started) * 1000),
        )

    # Only LENGTH and emphasis go to the prompt; order and hiding are read-time (apply_style).
    style = prompt_style_string(current_style(session_factory))
    prompt = render_brief_prompt(
        persona=persona, inputs=inputs, evidence_text=table.render(), style_profile=style
    )
    llm_started = time.monotonic()
    draft = await llm.complete_json(prompt, BriefDraft, temperature=BRIEF_TEMPERATURE)
    timings.set("p3", time.monotonic() - llm_started)
    logger.info("brief.llm meeting=%s mode=%s duration_ms=%d", meeting_id, mode, timings.ms["p3"])

    post_started = time.monotonic()
    brief_id, generated_at = new_brief_stamp(session_factory, meeting_id, mode)
    brief = assemble_brief(
        draft,
        table,
        mode=mode,
        inputs=inputs,
        meetings=meetings,
        brief_id=brief_id,
        generated_at=generated_at,
        competitor_hits=competitor_hits if with_memory else (),
        competitors=persona.competitors if with_memory else (),
        cross_contact_alerts=cross_contact_alerts if with_memory else (),
        cross_deal_patterns=cross_deal_patterns if with_memory else (),
        deal_snapshot=context.deal_snapshot if with_memory else (),
    )
    if with_memory and not brief.sections:
        # Never persist (and so never serve from the cache) a brief with nothing in it.
        logger.warning("brief.empty_not_persisted meeting=%s mode=%s", meeting_id, mode)
    else:
        brief = save_brief(session_factory, brief)
    timings.set("post", time.monotonic() - post_started)
    total = time.monotonic() - started
    timings.set("total", total)
    logger.info(
        "brief.done meeting=%s mode=%s items=%d duration_ms=%d",
        meeting_id,
        mode,
        sum(len(s.items) for s in brief.sections),
        timings.ms["total"],
    )
    ms = timings.ms
    timing_logger.info(
        "brief.timing meeting=%s mode=%s load_ms=%d recall_ms=%d reflect_ms=%d resolve_ms=%d "
        "mental_model_ms=%d gather_ms=%d p3_ms=%d post_ms=%d total_ms=%d",
        meeting_id,
        mode,
        ms.get("load", 0),
        ms.get("recall", 0),
        ms.get("reflect", 0),
        ms.get("resolve", 0),
        ms.get("mental_model", 0),
        ms.get("gather", 0),
        ms.get("p3", 0),
        ms.get("post", 0),
        ms.get("total", 0),
    )
    return brief


async def get_cached_brief(
    meeting_id: str, mode: BriefMode, *, session_factory: SessionFactory
) -> Brief | None:
    """The stored brief, or None if there is none or the account ingested a meeting since."""
    return get_fresh_brief(session_factory, meeting_id, mode)
