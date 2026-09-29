"""Fake-backed behavioral tests for the `MemoryService` interface
(docs/hindsight-integration.md "memory_service interface" / "Testing"),
covering bootstrap, retain, recall, reflect, mental models and
`wait_until_idle` -- no network, per that doc's `FakeMemoryService` contract.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import BaseModel

from app.memory.tags import account_tag, contact_tag
from app.schemas.enums import FactKind, ScopeType
from app.schemas.memory import MemoryHit, ReflectResult
from tests.fakes.fake_memory_service import FakeMemoryService, _RetainedItem


@pytest.fixture
def memory() -> FakeMemoryService:
    return FakeMemoryService()


class _TinySchema(BaseModel):
    answer: str


# -- bootstrap --------------------------------------------------------------


async def test_ensure_bank_is_idempotent(memory: FakeMemoryService) -> None:
    await memory.ensure_bank()
    await memory.ensure_bank()
    assert memory.bank_ensured is True


async def test_ensure_mental_models_creates_one_per_account_plus_style(
    memory: FakeMemoryService,
) -> None:
    await memory.ensure_mental_models([("acc_finedge", "FinEdge"), ("acc_tracewise", "Tracewise")])

    assert await memory.get_mental_model("relationship-acc_finedge") is not None
    assert await memory.get_mental_model("relationship-acc_tracewise") is not None
    assert await memory.get_mental_model("style-fake-user") is not None
    assert await memory.get_mental_model("relationship-acc_nonexistent") is None


async def test_ensure_mental_models_does_not_duplicate_existing(
    memory: FakeMemoryService,
) -> None:
    memory.seed_mental_model("relationship-acc_finedge", name="Custom", content="curated")

    await memory.ensure_mental_models([("acc_finedge", "FinEdge")])

    model = await memory.get_mental_model("relationship-acc_finedge")
    assert model is not None
    assert model.content == "curated"  # not overwritten


# -- retain -------------------------------------------------------------------


async def test_retain_meeting_tags_account_contacts_meeting_and_kind(
    memory: FakeMemoryService,
) -> None:
    await memory.retain_meeting(
        meeting_id="m4_finedge",
        account_id="acc_finedge",
        contact_ids=["c_rahul", "c_karan"],
        meeting_date=date(2026, 8, 27),
        title="Pilot scoping",
        transcript="Rahul: we need SOC 2 before we can move forward.",
    )

    assert len(memory.items) == 1
    item = memory.items[0]
    assert item.tags == [
        "account:acc_finedge",
        "contact:c_rahul",
        "contact:c_karan",
        "meeting:m4_finedge",
        "kind:transcript",
    ]
    assert item.meeting_id == "m4_finedge"
    assert item.meeting_date == date(2026, 8, 27)


async def test_retain_note_adds_scope_tag(memory: FakeMemoryService) -> None:
    await memory.retain_note(
        text="Prefers async updates", scope_type=ScopeType.contact, scope_id="c_anita"
    )

    assert len(memory.items) == 1
    assert "kind:note" in memory.items[0].tags
    assert contact_tag("c_anita") in memory.items[0].tags


async def test_retain_preference_has_no_account_tag(memory: FakeMemoryService) -> None:
    await memory.retain_preference("On 2026-09-28 the user collapsed personal touchpoints.")

    assert memory.items[0].tags == ["kind:preference"]
    assert not any(t.startswith("account:") for t in memory.items[0].tags)


# -- recall ---------------------------------------------------------------------


async def test_recall_facts_filters_by_tags_all_strict_and_keyword(
    memory: FakeMemoryService,
) -> None:
    await memory.retain_meeting(
        meeting_id="m4_finedge",
        account_id="acc_finedge",
        contact_ids=["c_rahul"],
        meeting_date=date(2026, 8, 27),
        title="Pilot scoping",
        transcript="Rahul mentioned SOC 2 compliance is a blocker for procurement.",
    )
    await memory.retain_meeting(
        meeting_id="m5_finedge",
        account_id="acc_finedge",
        contact_ids=["c_anita"],
        meeting_date=date(2026, 9, 1),
        title="Follow-up",
        transcript="Anita talked about her upcoming vacation plans.",
    )

    hits = await memory.recall_facts(
        query="SOC 2 compliance", tags=[account_tag("acc_finedge")], fact_kind=None
    )
    assert len(hits) == 1
    assert hits[0].meeting_id == "m4_finedge"


async def test_recall_facts_excludes_items_missing_a_required_tag(
    memory: FakeMemoryService,
) -> None:
    await memory.retain_note(
        text="Loves the SOC 2 update", scope_type=ScopeType.account, scope_id="acc_other"
    )

    hits = await memory.recall_facts(query="SOC 2", tags=[account_tag("acc_finedge")])
    assert hits == []


async def test_recall_facts_appends_fact_kind_tag(memory: FakeMemoryService) -> None:
    memory.items.append(
        _RetainedItem(
            memory_id="mem-1",
            text="Anita's kid started college this fall.",
            tags=[account_tag("acc_finedge"), contact_tag("c_anita"), "fact_kind:personal"],
        )
    )
    memory.items.append(
        _RetainedItem(
            memory_id="mem-2",
            text="Deal budget is about $40K.",
            tags=[account_tag("acc_finedge"), contact_tag("c_anita"), "fact_kind:deal_fact"],
        )
    )

    hits = await memory.recall_facts(
        query="Anita", tags=[contact_tag("c_anita")], fact_kind=FactKind.personal
    )
    assert [h.memory_id for h in hits] == ["mem-1"]


# -- reflect ----------------------------------------------------------------------


async def test_reflect_structured_returns_queued_response(memory: FakeMemoryService) -> None:
    canned = ReflectResult(
        text="",
        structured={"answer": "SOC 2 is still open"},
        sources=[
            MemoryHit(
                memory_id="mem-1",
                text="SOC 2 pending",
                meeting_id="m4_finedge",
                meeting_date=date(2026, 8, 27),
                tags=["account:acc_finedge"],
            )
        ],
        structured_error=None,
    )
    memory.queue_reflect_response(canned)

    result = await memory.reflect_structured(
        query="What objections are unresolved?",
        tags=[account_tag("acc_finedge")],
        schema=_TinySchema,
        budget="mid",
    )

    assert result is canned
    assert memory.reflect_calls == [
        ("What objections are unresolved?", [account_tag("acc_finedge")], "mid")
    ]


async def test_reflect_structured_raises_queued_error(memory: FakeMemoryService) -> None:
    memory.queue_reflect_error(RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        await memory.reflect_structured(
            query="q", tags=[], schema=_TinySchema, budget="high"
        )


async def test_reflect_structured_without_queued_response_raises_assertion(
    memory: FakeMemoryService,
) -> None:
    with pytest.raises(AssertionError):
        await memory.reflect_structured(query="q", tags=[], schema=_TinySchema)


# -- mental models ------------------------------------------------------------------


async def test_get_mental_model_returns_none_when_missing(memory: FakeMemoryService) -> None:
    assert await memory.get_mental_model("relationship-acc_missing") is None


# -- timeline -----------------------------------------------------------------------


async def test_timeline_sorted_by_meeting_date(memory: FakeMemoryService) -> None:
    await memory.retain_meeting(
        meeting_id="m5",
        account_id="acc_finedge",
        contact_ids=["c_anita"],
        meeting_date=date(2026, 9, 1),
        title="Later",
        transcript="second",
    )
    await memory.retain_meeting(
        meeting_id="m4",
        account_id="acc_finedge",
        contact_ids=["c_anita"],
        meeting_date=date(2026, 8, 27),
        title="Earlier",
        transcript="first",
    )

    hits = await memory.timeline("c_anita")
    assert [h.meeting_id for h in hits] == ["m4", "m5"]


# -- wait_until_idle ------------------------------------------------------------------


async def test_wait_until_idle_returns_true(memory: FakeMemoryService) -> None:
    assert await memory.wait_until_idle(timeout_s=1.0) is True


# -- close ------------------------------------------------------------------------------


async def test_aclose_marks_closed(memory: FakeMemoryService) -> None:
    await memory.aclose()
    assert memory.closed is True


# -- fake fidelity (Phase 3 commit 0) -------------------------------------------


async def test_fake_retain_meeting_populates_hit_metadata(memory: FakeMemoryService) -> None:
    await memory.retain_meeting(
        meeting_id="m1_x",
        account_id="acc_x",
        contact_ids=["con_a"],
        meeting_date=date(2026, 5, 1),
        title="Kickoff",
        transcript="pricing discussed",
        source="seed",
    )

    (hit,) = await memory.recall_facts(query="pricing", tags=[account_tag("acc_x")])
    assert hit.meeting_id == "m1_x"
    assert hit.meeting_date == date(2026, 5, 1)

    (record,) = memory.items
    assert record.document_id == "meeting-m1_x"
    assert record.title == "Kickoff"
    assert record.source == "seed"
    assert account_tag("acc_x") in record.tags
    assert contact_tag("con_a") in record.tags


async def test_fake_reretain_same_document_replaces_hits(memory: FakeMemoryService) -> None:
    async def retain(transcript: str) -> None:
        await memory.retain_meeting(
            meeting_id="m1_x",
            account_id="acc_x",
            contact_ids=["con_a"],
            meeting_date=date(2026, 5, 1),
            title="Kickoff",
            transcript=transcript,
        )

    await retain("first version")
    await retain("second version")
    await memory.retain_note(text="a note", scope_type=ScopeType.account, scope_id="acc_x")

    meeting_records = [i for i in memory.items if i.document_id == "meeting-m1_x"]
    assert len(meeting_records) == 1
    assert meeting_records[0].text == "second version"
    assert len(memory.items) == 2  # notes are untouched
