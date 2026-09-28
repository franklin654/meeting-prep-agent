"""Extraction output: docs/data-model-and-schemas.md "Extraction output".

One LLM call per ingested transcript (prompt P1) returns `MeetingExtraction`;
it feeds entity resolution and the commitments ledger only, since Hindsight
gets the raw transcript. All models here are LLM-facing output, so they
forbid extra fields per the doc's "Conventions" section.

Rules (enforced in code, not here): `source_quote` must appear verbatim in
the transcript; failing items are dropped. Matching an `Acknowledgement` to
an open commitment is a separate, small LLM call (prompt P2).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from app.schemas.enums import FactKind, Owner


class PersonMention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_as_said: str  # "KS", "Rahul", "their CFO"
    role_if_stated: str | None
    organisation: str | None  # "FinEdge", "Tracewise"


class ExtractedCommitment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner: Owner
    owner_person: str  # name_as_said of who promised
    text: str  # "Send revised pricing deck with pilot option"
    due_date: date | None  # resolved against meeting date; None if not stated
    source_quote: str  # exact words from transcript, <= 200 chars


class Acknowledgement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str  # "SOC 2 report received"
    source_quote: str


class ExtractedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: FactKind  # never "commitment" here; those go above
    about_person: str | None
    text: str
    source_quote: str


class MeetingExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    people: list[PersonMention]
    commitments: list[ExtractedCommitment]
    acknowledgements: list[Acknowledgement]  # used to close open commitments
    facts: list[ExtractedFact]  # shown in the "learned" toast
    deal_budget_usd: int | None  # only if a number is stated
