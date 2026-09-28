"""Pydantic models and enums that are the contract between backend modules.

Copied from docs/data-model-and-schemas.md ("the source of truth for every
model"); if code and that doc disagree, the doc wins (see AGENTS.md).

Organised by the doc's own sections:

- `enums`: shared `StrEnum`s from the "Conventions" section.
- `extraction`: `MeetingExtraction` and friends (P1 output).
- `brief`: `BriefDraft` (LLM output) through the stored `Brief` (API/DB shape).
- `ask`: Ask panel request/response models.
- `memory`: `MemoryHit` / `ReflectResult`, the memory_service return types.
- `api`: remaining request/response bodies for `/api/*` routes.

This package holds Pydantic models only. SQLModel tables live in `app/db`
(ticket T06); the Hindsight bank config (`BANK_ID`, `BANK_CONFIG`) and tag
builders live in `app/memory` (ticket T07) since they are plain constants
and functions, not Pydantic models, and depend on `app.config.settings`.
"""

from __future__ import annotations

from app.schemas.api import (
    ContactRef,
    ContactTimeline,
    ErrorBody,
    ErrorResponse,
    FeedbackRequest,
    JobAccepted,
    JobStatus,
    LearnedSummary,
    MeetingSummary,
    NotesRequest,
    Nudge,
    StyleProfile,
    TimelineEntry,
)
from app.schemas.ask import (
    UNGROUNDED_REPLY,
    AskRequest,
    AskResponse,
    AskTurn,
    NoteRequest,
    PinRequest,
    ReflectAnswer,
)
from app.schemas.brief import (
    Brief,
    BriefDraft,
    BriefItem,
    BriefSection,
    Citation,
    DraftItem,
    SectionKey,
    Severity,
    SourceType,
)
from app.schemas.enums import CommitmentStatus, FactKind, Owner, ScopeType
from app.schemas.extraction import (
    Acknowledgement,
    ExtractedCommitment,
    ExtractedFact,
    MeetingExtraction,
    PersonMention,
)
from app.schemas.memory import MemoryHit, ReflectResult

__all__ = [
    "UNGROUNDED_REPLY",
    "Acknowledgement",
    "AskRequest",
    "AskResponse",
    "AskTurn",
    "Brief",
    "BriefDraft",
    "BriefItem",
    "BriefSection",
    "Citation",
    "CommitmentStatus",
    "ContactRef",
    "ContactTimeline",
    "DraftItem",
    "ErrorBody",
    "ErrorResponse",
    "ExtractedCommitment",
    "ExtractedFact",
    "FactKind",
    "FeedbackRequest",
    "JobAccepted",
    "JobStatus",
    "LearnedSummary",
    "MeetingExtraction",
    "MeetingSummary",
    "MemoryHit",
    "NoteRequest",
    "NotesRequest",
    "Nudge",
    "Owner",
    "PersonMention",
    "PinRequest",
    "ReflectAnswer",
    "ReflectResult",
    "ScopeType",
    "SectionKey",
    "Severity",
    "SourceType",
    "StyleProfile",
    "TimelineEntry",
]
