"""Round-trip tests for docs/data-model-and-schemas.md "Extraction output" (T05)."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas.enums import FactKind, Owner
from app.schemas.extraction import (
    Acknowledgement,
    ExtractedCommitment,
    ExtractedFact,
    MeetingExtraction,
    PersonMention,
)
from tests.unit.schema_helpers import round_trip


def _meeting_extraction() -> MeetingExtraction:
    return MeetingExtraction(
        people=[
            PersonMention(name_as_said="KS", role_if_stated="CFO", organisation="FinEdge"),
            PersonMention(name_as_said="Rahul", role_if_stated=None, organisation=None),
        ],
        commitments=[
            ExtractedCommitment(
                owner=Owner.us,
                owner_person="Priya",
                text="Send revised pricing deck with pilot option",
                due_date=date(2026, 9, 5),
                source_quote="I'll send the revised pricing deck by Friday",
            ),
            ExtractedCommitment(
                owner=Owner.them,
                owner_person="Rahul",
                text="Share SOC 2 report",
                due_date=None,
                source_quote="I'll get you the SOC 2 report",
            ),
        ],
        acknowledgements=[
            Acknowledgement(description="SOC 2 report received", source_quote="got the report"),
        ],
        facts=[
            ExtractedFact(
                kind=FactKind.deal_fact,
                about_person=None,
                text="Budget now $75K",
                source_quote="budget moved to about 75K",
            ),
            ExtractedFact(
                kind=FactKind.personal,
                about_person="Rahul",
                text="Rahul's kid started college",
                source_quote="my daughter just started college",
            ),
        ],
        deal_budget_usd=75000,
    )


def test_meeting_extraction_round_trips() -> None:
    round_trip(_meeting_extraction())


def test_meeting_extraction_round_trips_with_null_optionals() -> None:
    extraction = MeetingExtraction(
        people=[],
        commitments=[],
        acknowledgements=[],
        facts=[],
        deal_budget_usd=None,
    )
    round_trip(extraction)


@pytest.mark.parametrize(
    "build",
    [
        lambda: PersonMention(
            name_as_said="KS", role_if_stated="CFO", organisation="FinEdge", extra_field="x"
        ),
        lambda: ExtractedCommitment(
            owner=Owner.us,
            owner_person="Priya",
            text="Send deck",
            due_date=None,
            source_quote="quote",
            extra_field="x",
        ),
        lambda: Acknowledgement(description="d", source_quote="q", extra_field="x"),
        lambda: ExtractedFact(
            kind=FactKind.personal,
            about_person=None,
            text="t",
            source_quote="q",
            extra_field="x",
        ),
        lambda: MeetingExtraction(
            people=[],
            commitments=[],
            acknowledgements=[],
            facts=[],
            deal_budget_usd=None,
            extra_field="x",
        ),
    ],
)
def test_extraction_models_forbid_extra_fields(build: object) -> None:
    with pytest.raises(ValidationError):
        build()  # type: ignore[operator]
