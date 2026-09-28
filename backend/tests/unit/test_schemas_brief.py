"""Round-trip tests for docs/data-model-and-schemas.md "Brief output" (T05)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

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
from tests.unit.schema_helpers import round_trip


def test_section_key_and_severity_and_source_type_values() -> None:
    assert {m.value for m in SectionKey} == {
        "attendees",
        "where_left_off",
        "open_commitments",
        "unresolved_objections",
        "personal_touchpoints",
        "agenda",
        "watch_outs",
        "alerts",
        "your_questions",
    }
    assert {m.value for m in Severity} == {"info", "warning", "critical"}
    assert {m.value for m in SourceType} == {"meeting", "ledger", "mental_model", "ask"}


def test_draft_item_defaults_and_round_trip() -> None:
    item = DraftItem(text="Pricing deck still not sent", evidence_ids=["led:cm_ab12cd34"])
    assert item.severity == Severity.info
    assert item.contact_ids == []
    round_trip(item)

    item_full = DraftItem(
        text="Budget contradiction",
        severity=Severity.critical,
        contact_ids=["c_rahul"],
        evidence_ids=["mem:abc123", "mem:def456"],
    )
    round_trip(item_full)


def test_brief_draft_round_trips_with_section_key_dict() -> None:
    draft = BriefDraft(
        sections={
            SectionKey.open_commitments: [
                DraftItem(text="Send pricing deck", evidence_ids=["led:cm_ab12cd34"]),
            ],
            SectionKey.watch_outs: [],
        }
    )
    round_trip(draft)


def test_draft_item_and_brief_draft_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError):
        DraftItem(text="t", evidence_ids=[], extra_field="x")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        BriefDraft(sections={}, extra_field="x")  # type: ignore[call-arg]


def _citation() -> Citation:
    return Citation(
        source_type=SourceType.meeting,
        meeting_id="m4_finedge",
        meeting_date=date(2026, 8, 27),
        label="Call on Aug 27, 2026",
        quote="I'll send the revised pricing deck by Friday",
        memory_id="mem_abc123",
    )


def test_citation_round_trips_including_all_null_optionals() -> None:
    round_trip(_citation())
    round_trip(
        Citation(
            source_type=SourceType.ledger,
            meeting_id=None,
            meeting_date=None,
            label="Open commitment",
            quote=None,
            memory_id=None,
        )
    )


def test_brief_item_and_section_and_brief_round_trip() -> None:
    item = BriefItem(
        id="bi_1",
        text="Pricing deck still not sent",
        severity=Severity.warning,
        contact_ids=["c_rahul"],
        citations=[_citation()],
    )
    round_trip(item)

    section = BriefSection(
        key=SectionKey.open_commitments,
        title="Open commitments",
        items=[item],
        collapsed=True,
    )
    round_trip(section)

    brief = Brief(
        id="br_1a2b3c4d",
        meeting_id="m5_finedge",
        mode="memory",
        generated_at=datetime(2026, 9, 28, 9, 0, tzinfo=UTC),
        sections=[section],
        facts_used=12,
        preferences_applied=["collapsed personal_touchpoints"],
    )
    round_trip(brief)


def test_brief_mode_rejects_values_outside_literal() -> None:
    with pytest.raises(ValidationError):
        Brief(
            id="br_1",
            meeting_id="m1",
            mode="both",  # type: ignore[arg-type]
            generated_at=datetime(2026, 9, 28, tzinfo=UTC),
            sections=[],
            facts_used=0,
            preferences_applied=[],
        )
