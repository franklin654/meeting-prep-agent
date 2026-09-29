"""Pure mapping-logic unit tests for `HindsightMemoryService`'s SDK-response ->
schema-type conversion (`_hit_from_recall_result`, `_hit_from_reflect_fact`).

No network: these pass lightweight stand-ins with exactly the attribute names
of the real `hindsight_client_api` response models (confirmed via
`inspect`/`.model_fields` against the installed `hindsight-client==0.10.1`
package -- see memory_service.py's module docstring), not the real SDK
classes -- constructing those requires a live call. The live contract test
(tests/live/test_memory_contract.py) exercises the real objects end to end.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.memory.memory_service import (
    _demo_today_iso,
    _hit_from_recall_result,
    _hit_from_reflect_fact,
    _relationship_model_id,
    _style_model_id,
)


@dataclass
class _StubRecallResult:
    """Same field names as `hindsight_client_api.models.recall_result.RecallResult`."""

    id: str
    text: str
    tags: list[str] | None
    metadata: dict[str, str] | None


@dataclass
class _StubReflectFact:
    """Same field names as `hindsight_client_api.models.reflect_fact.ReflectFact`."""

    id: str
    text: str
    occurred_start: datetime | None


def test_hit_from_recall_result_reads_meeting_metadata_and_tags() -> None:
    stub = _StubRecallResult(
        id="fact-1",
        text="SOC 2 report received",
        tags=["account:acc_finedge", "meeting:m4_finedge"],
        metadata={"meeting_id": "m4_finedge", "meeting_date": "2026-08-27", "title": "Pilot"},
    )

    hit = _hit_from_recall_result(stub)

    assert hit.memory_id == "fact-1"
    assert hit.text == "SOC 2 report received"
    assert hit.meeting_id == "m4_finedge"
    assert hit.meeting_date == date(2026, 8, 27)
    assert hit.tags == ["account:acc_finedge", "meeting:m4_finedge"]


def test_hit_from_recall_result_handles_missing_metadata_and_tags() -> None:
    stub = _StubRecallResult(id="fact-2", text="untagged fact", tags=None, metadata=None)

    hit = _hit_from_recall_result(stub)

    assert hit.meeting_id is None
    assert hit.meeting_date is None
    assert hit.tags == []


def test_hit_from_reflect_fact_has_no_meeting_id_or_tags() -> None:
    # ReflectFact (from reflect's based_on.memories) carries none of the tags/
    # metadata/document_id that RecallResult does -- see memory_service.py's
    # `_hit_from_reflect_fact` docstring comment.
    stub = _StubReflectFact(
        id="fact-3", text="Budget is about $40K", occurred_start=datetime(2026, 8, 27, 10, 0)
    )

    hit = _hit_from_reflect_fact(stub)

    assert hit.memory_id == "fact-3"
    assert hit.meeting_id is None
    assert hit.tags == []
    # occurred_start is an event date in the text, never the meeting date.
    assert hit.meeting_date is None


def test_hit_from_reflect_fact_handles_missing_occurred_start() -> None:
    stub = _StubReflectFact(id="fact-4", text="no date", occurred_start=None)

    hit = _hit_from_reflect_fact(stub)

    assert hit.meeting_date is None


def test_demo_today_iso_uses_settings_demo_today() -> None:
    iso = _demo_today_iso()
    assert iso.startswith("2026-09-28")


def test_mental_model_id_helpers_are_stable_and_lowercase() -> None:
    assert _relationship_model_id("acc_finedge") == "relationship-acc_finedge"
    assert _style_model_id().startswith("style-")
