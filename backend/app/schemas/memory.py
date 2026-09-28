"""Hindsight model return types: docs/data-model-and-schemas.md "Hindsight model"
and docs/hindsight-integration.md "memory_service interface".

`MemoryHit` and `ReflectResult` are what `memory_service.py` (ticket T07)
returns from `recall_facts` / `reflect_structured` / `timeline` -- schema
types, never raw SDK objects, per that module's contract.

`BANK_ID`, `BANK_CONFIG` and the tag vocabulary from the same doc section
are not Pydantic models (a formatted string and a plain dict) and depend on
`app.config.settings` and tag-building helpers; they belong with
`app/memory/memory_service.py` and `app/memory/tags.py` (ticket T07), not
here. Left out of this ticket's scope; noted in the ticket report.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel


class MemoryHit(BaseModel):
    memory_id: str
    text: str
    meeting_id: str | None  # from document metadata
    meeting_date: date | None
    tags: list[str]


class ReflectResult(BaseModel):
    text: str  # markdown answer
    # doc writes `dict | None`; `dict[str, Any]` to satisfy mypy --strict
    # (disallow_any_generics), same runtime shape as `structured_output`.
    structured: dict[str, Any] | None
    sources: list[MemoryHit]  # from based_on.memories
    structured_error: str | None  # structured_output_error
