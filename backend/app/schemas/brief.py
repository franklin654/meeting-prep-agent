"""Brief output: docs/data-model-and-schemas.md "Brief output".

The LLM (prompt P3) returns a `BriefDraft` that points at evidence ids it
was given (`mem:<hindsight_id>`, `led:<commitment_id>`, `mm:<mental_model_id>`,
`ask:<ask_id>`); code turns those ids into `Citation` objects and drops
anything it can't resolve, producing the stored `Brief`.

`BriefDraft` and `DraftItem` are LLM-facing output, so they forbid extra
fields. `Citation`, `BriefItem`, `BriefSection` and `Brief` are the
API/DB shape code builds from the draft, matching the doc (no `extra`
forbidding there).

Validation (enforced in code, not here): in `memory` mode every `BriefItem`
has at least one citation; in `no_memory` mode citations are empty by
design and the UI labels the brief "No memory".
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class SectionKey(StrEnum):
    attendees = "attendees"
    where_left_off = "where_left_off"
    open_commitments = "open_commitments"
    unresolved_objections = "unresolved_objections"
    personal_touchpoints = "personal_touchpoints"
    agenda = "agenda"
    watch_outs = "watch_outs"
    alerts = "alerts"
    your_questions = "your_questions"


class Severity(StrEnum):
    info = "info"
    warning = "warning"
    critical = "critical"  # neutral / amber / red


# ---- what the LLM returns ----
class DraftItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    severity: Severity = Severity.info
    contact_ids: list[str] = []
    evidence_ids: list[str]  # ids from the evidence list in the prompt


class BriefDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sections: dict[SectionKey, list[DraftItem]]


# ---- what the API returns and the DB stores ----
class SourceType(StrEnum):
    meeting = "meeting"
    ledger = "ledger"
    mental_model = "mental_model"
    ask = "ask"


class Citation(BaseModel):
    source_type: SourceType
    meeting_id: str | None
    meeting_date: date | None
    label: str  # "Call on Aug 27, 2026"
    quote: str | None  # short supporting text, <= 200 chars
    memory_id: str | None  # Hindsight memory id when available


class BriefItem(BaseModel):
    id: str
    text: str
    severity: Severity
    contact_ids: list[str]
    citations: list[Citation]


class BriefSection(BaseModel):
    key: SectionKey
    title: str
    items: list[BriefItem]
    collapsed: bool = False  # from style profile


class OwedItem(BaseModel):
    text: str
    due_date: date | None
    status: Literal["open", "overdue"]
    days_overdue: int
    owner_name: str
    severity: Severity
    citations: list[Citation]


class RankedObjection(BaseModel):
    topic: str
    count: int
    dates: list[date]
    citations: list[Citation]


class ContactCard(BaseModel):
    name: str
    role: str | None
    account: str
    style: str | None = None
    style_citations: list[Citation] = []
    recent_meetings: list[Citation] = []
    open_follow_ups: int = 0


class Brief(BaseModel):
    id: str
    meeting_id: str
    mode: Literal["memory", "no_memory"]
    generated_at: datetime
    sections: list[BriefSection]  # ordered by style profile
    facts_used: int  # personalization meter
    preferences_applied: list[str]
    you_owe: list[OwedItem] = []
    they_owe: list[OwedItem] = []
    objections: list[RankedObjection] = []
    memory_used: dict[str, int] = {"facts": 0, "meetings": 0}
    contact_cards: list[ContactCard] = []
    first_meeting: bool = False
