"""Strict LLM output and response models for explicit contact pattern refresh."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.brief import Citation


class ContactPatternSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=5, max_length=240)
    fact_ids: list[str] = Field(min_length=1, max_length=10)


class ContactPatternDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patterns: list[ContactPatternSuggestion] = Field(default_factory=list, max_length=4)


class ContactPattern(BaseModel):
    text: str
    fact_ids: list[str]
    citations: list[Citation]


class PatternRefreshResponse(BaseModel):
    patterns: list[ContactPattern]
    reason: Literal[
        "Needs facts from at least 2 meetings", "Needs at least 3 visible facts"
    ] | None = None
