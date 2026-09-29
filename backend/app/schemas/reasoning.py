"""Structured outputs for Hindsight reasoning operations (R2 and later)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict


class Contradiction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    topic: str
    earlier_value: str
    earlier_date: date
    new_value: str
    new_date: date
    summary: str


class ContradictionReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    contradictions: list[Contradiction]


class Gap(BaseModel):
    model_config = ConfigDict(extra="ignore")

    concern: str
    raised_by: str
    answered_on: date | None = None
    not_heard_by: list[str]


class GapReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    gaps: list[Gap]


class Pattern(BaseModel):
    model_config = ConfigDict(extra="ignore")

    objection: str
    other_account: str
    what_worked: str
    resolved_on: date


class PatternReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    patterns: list[Pattern]
