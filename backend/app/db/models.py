"""SQLModel tables: docs/data-model-and-schemas.md ("SQLite tables").

Nine tables, copied field-for-field from that doc (the source of truth on
any conflict). JSON columns hold nested Pydantic data (brief content,
answers) as plain `dict`; nothing about memory itself is stored here — see
`app/memory/memory_service.py` for that gateway.

Overdue is computed, never stored: `status == open and due_date <
settings.demo_today` (see `repository.list_overdue_commitments`, which reads
"today" through `app.core.time.today()` per AGENTS.md hard rule 6).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import UniqueConstraint
from sqlmodel import JSON, Column, Field, SQLModel

from app.schemas.brief import SectionKey
from app.schemas.enums import CommitmentStatus, FactKind, Owner, ScopeType


class Account(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    industry: str
    size: int | None = None
    stage: str  # discovery | evaluation | closed_won | closed_lost
    deal_value_usd: int | None = None


class Contact(SQLModel, table=True):
    id: str = Field(primary_key=True)
    account_id: str | None = Field(foreign_key="account.id")  # None for our own people
    name: str
    aliases: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    role: str | None = None
    needs_review: bool = False  # created by entity resolution, unconfirmed


class Meeting(SQLModel, table=True):
    id: str = Field(primary_key=True)
    account_id: str = Field(foreign_key="account.id", index=True)
    title: str
    scheduled_at: datetime
    status: str  # upcoming | done
    transcript: str | None = None
    ingested_at: datetime | None = None


class MeetingAttendee(SQLModel, table=True):
    meeting_id: str = Field(foreign_key="meeting.id", primary_key=True)
    contact_id: str = Field(foreign_key="contact.id", primary_key=True)


class Commitment(SQLModel, table=True):
    id: str = Field(primary_key=True)
    account_id: str = Field(foreign_key="account.id", index=True)
    meeting_id: str = Field(foreign_key="meeting.id")
    owner: Owner
    contact_id: str | None = Field(default=None, foreign_key="contact.id")
    text: str
    due_date: date | None = None
    status: CommitmentStatus = CommitmentStatus.open
    source_quote: str
    closed_by_meeting_id: str | None = None


class BriefRecord(SQLModel, table=True):
    # One stored brief per meeting and mode; makes concurrent upserts safe (see brief_repo).
    __table_args__ = (UniqueConstraint("meeting_id", "mode", name="ux_briefrecord_meeting_mode"),)

    id: str = Field(primary_key=True)
    meeting_id: str = Field(foreign_key="meeting.id", index=True)
    mode: str  # memory | no_memory
    # doc writes `dict`; `dict[str, Any]` to satisfy mypy --strict (see app/schemas/memory.py).
    content: dict[str, Any] = Field(sa_column=Column(JSON))  # Brief.model_dump(mode="json")
    created_at: datetime


class Feedback(SQLModel, table=True):
    id: str = Field(primary_key=True)
    brief_id: str = Field(foreign_key="briefrecord.id")
    section: SectionKey
    action: str  # up | down | more | less | collapsed
    created_at: datetime


class AskAnswer(SQLModel, table=True):
    id: str = Field(primary_key=True)
    scope_type: ScopeType
    scope_id: str
    question: str
    # doc writes `dict`; `dict[str, Any]` to satisfy mypy --strict (see app/schemas/memory.py).
    answer: dict[str, Any] = Field(sa_column=Column(JSON))  # AskResponse minus id
    pinned_to_meeting_id: str | None = Field(default=None, foreign_key="meeting.id")
    created_at: datetime


class Job(SQLModel, table=True):
    id: str = Field(primary_key=True)
    kind: str  # ingest | note | reasoning | capture_preview | capture_save
    status: str  # pending | done | failed
    # doc writes `dict | None`; `dict[str, Any] | None` to satisfy mypy --strict.
    result: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class ExtractedFact(SQLModel, table=True):
    id: str = Field(primary_key=True)
    account_id: str = Field(foreign_key="account.id", index=True)
    meeting_id: str = Field(foreign_key="meeting.id", index=True)
    contact_id: str | None = Field(default=None, foreign_key="contact.id")
    kind: FactKind
    text: str
    source_quote: str
    created_at: datetime


class CaptureDraft(SQLModel, table=True):
    id: str = Field(primary_key=True)
    meeting_id: str = Field(foreign_key="meeting.id", index=True)
    transcript: str
    extraction: dict[str, Any] = Field(sa_column=Column(JSON))
    items: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    status: str = "open"  # open | saved | discarded
    created_at: datetime


class MeetingPrepared(SQLModel, table=True):
    meeting_id: str = Field(foreign_key="meeting.id", primary_key=True)
    prepared_at: datetime


class MemoryOverride(SQLModel, table=True):
    id: str = Field(primary_key=True)
    target_type: str  # fact | memory
    target_id: str
    action: str  # hidden | corrected
    corrected_text: str | None = None
    created_at: datetime


class ContactPatternCache(SQLModel, table=True):
    contact_id: str = Field(primary_key=True, foreign_key="contact.id")
    patterns: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    refreshed_at: datetime
