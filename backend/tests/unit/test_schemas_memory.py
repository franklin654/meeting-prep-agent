"""Round-trip tests for docs/data-model-and-schemas.md "Hindsight model"
(`MemoryHit`, `ReflectResult`) (T05)."""

from __future__ import annotations

from datetime import date

from app.schemas.memory import MemoryHit, ReflectResult
from tests.unit.schema_helpers import round_trip


def _hit() -> MemoryHit:
    return MemoryHit(
        memory_id="mem_abc123",
        text="Budget moved to about $75K",
        meeting_id="m5_finedge",
        meeting_date=date(2026, 9, 2),
        tags=["account:acc_finedge", "fact_kind:deal_fact"],
    )


def test_memory_hit_round_trips_including_null_optionals() -> None:
    round_trip(_hit())
    round_trip(
        MemoryHit(
            memory_id="mem_xyz",
            text="untagged note",
            meeting_id=None,
            meeting_date=None,
            tags=[],
        )
    )


def test_reflect_result_round_trips_with_structured_output() -> None:
    result = ReflectResult(
        text="The budget has moved from $40K to $75K.",
        structured={"contradictions": [{"topic": "budget"}]},
        sources=[_hit()],
        structured_error=None,
    )
    round_trip(result)


def test_reflect_result_round_trips_with_structured_error() -> None:
    result = ReflectResult(
        text="No structured output.",
        structured=None,
        sources=[],
        structured_error="schema mismatch",
    )
    round_trip(result)
