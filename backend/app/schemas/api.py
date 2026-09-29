"""API models: docs/data-model-and-schemas.md "API models, jobs and errors".

Request and response bodies for the endpoints in the Technical design;
routes return these models directly so the OpenAPI spec, and the generated
frontend client, stay exact.

`ErrorBody` / `ErrorResponse` document the error shape `app/core/errors.py`
(ticket T01) already serialises by hand (`{"error": {"code", "message"}}`);
they are not wired into that handler by this ticket (out of this ticket's
scope -- see the ticket report), but are here so routes can declare them as
an OpenAPI response model.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.brief import Citation, SectionKey
from app.schemas.enums import FactKind


class ContactRef(BaseModel):
    id: str
    name: str
    role: str | None


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    industry: str | None = Field(default=None, max_length=100)
    stage: Literal["discovery", "evaluation", "closed_won", "closed_lost"] = "discovery"


class AccountResponse(BaseModel):
    id: str
    name: str
    industry: str
    stage: Literal["discovery", "evaluation", "closed_won", "closed_lost"]


class ContactCreate(BaseModel):
    account_id: str
    name: str = Field(min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=200)
    aliases: list[str] = Field(default_factory=list)


class ContactSummary(ContactRef):
    account_id: str | None
    account_name: str | None
    meetings_count: int = 0
    open_followups: int = 0
    last_meeting_date: date | None = None


class MeetingCreate(BaseModel):
    account_id: str
    title: str = Field(min_length=1, max_length=200)
    scheduled_at: datetime
    attendee_ids: list[str] = Field(default_factory=list)


class MeetingSummary(BaseModel):  # GET /api/meetings
    id: str
    account_id: str
    account_name: str
    title: str
    scheduled_at: datetime
    status: str
    attendees: list[ContactRef]
    brief_ready: bool
    prepared: bool = False
    open_followups: int = 0
    past_meetings: int = 0
    has_history: bool = False


class NotesRequest(BaseModel):  # POST /api/meetings/{id}/notes
    transcript: str = Field(min_length=50)


class JobAccepted(BaseModel):  # 202 responses
    job_id: str


class LearnedSummary(BaseModel):
    facts: list[str]  # "Budget now $75K (was $40K)"
    new_commitments: int
    closed_commitments: int
    alerts: list[str]


class JobStatus(BaseModel):  # GET /api/jobs/{id}
    id: str
    kind: str
    status: Literal["pending", "done", "failed"]
    learned: LearnedSummary | None = None
    error: str | None = None


class TimelineEntry(BaseModel):  # GET /api/contacts/{id}/timeline
    text: str
    fact_kind: FactKind | None
    learned_on: date
    citation: Citation


class ContactTimeline(BaseModel):
    contact: ContactRef
    entries: list[TimelineEntry]  # newest first


class FeedbackRequest(BaseModel):  # POST /api/briefs/{id}/feedback
    section: SectionKey
    action: Literal["up", "down", "more", "less", "collapsed"]


class StyleProfile(BaseModel):
    section_order: list[SectionKey]
    hidden_sections: list[SectionKey]
    length: Literal["short", "standard", "detailed"]
    notes: list[str]  # plain-language rules shown in the UI


class Nudge(BaseModel):  # GET /api/nudges
    kind: Literal["overdue_commitment", "silent_contact", "brief_ready"]
    text: str
    link: str  # frontend route


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody
