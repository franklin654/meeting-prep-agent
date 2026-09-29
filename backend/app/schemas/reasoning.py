"""Structured outputs for Hindsight reasoning operations (R2 and later)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict


class Contradiction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    earlier_value: str
    earlier_date: date
    new_value: str
    new_date: date
    summary: str


class ContradictionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contradictions: list[Contradiction]
