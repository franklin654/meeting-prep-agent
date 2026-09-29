"""`resolve_sources`, the recall observation fix and `meeting_id_from_tags`.

Payload shapes follow the spike in docs/hindsight-integration.md ("Mapping a memory to
its meeting"): world facts carry metadata + document_id; observations have empty metadata
but a `meeting:<id>` tag and `mentioned_at`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pytest
from hindsight_client_api.exceptions import ApiException

from app.core.errors import MemoryUnavailableError
from app.memory.memory_service import HindsightMemoryService, _hit_from_recall_result
from app.memory.tags import account_tag, meeting_id_from_tags, meeting_tag
from app.schemas.memory import MemoryHit
from tests.fakes.fake_memory_service import FakeMemoryService


class _StubMemoryApi:
    def __init__(self, payloads: dict[str, Any]) -> None:
        self.payloads = payloads
        self.calls: list[str] = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def get_memory(self, bank_id: str, memory_id: str) -> Any:
        self.calls.append(memory_id)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0.005)
        self.in_flight -= 1
        if memory_id == "boom":
            raise ApiException(status=500, reason="boom")
        if memory_id not in self.payloads:
            raise ApiException(status=404, reason="nope")
        return self.payloads[memory_id]


class _StubClient:
    def __init__(self, payloads: dict[str, Any]) -> None:
        self.memory = _StubMemoryApi(payloads)


def _service(payloads: dict[str, Any]) -> tuple[HindsightMemoryService, _StubMemoryApi]:
    client = _StubClient(payloads)
    return HindsightMemoryService(client=client), client.memory  # type: ignore[arg-type]


def _hit(memory_id: str, text: str = "some fact") -> MemoryHit:
    return MemoryHit(memory_id=memory_id, text=text, meeting_id=None, meeting_date=None, tags=[])


WORLD = {
    "id": "w1",
    "text": "Deck promised",
    "tags": [account_tag("acc_x"), meeting_tag("m4_x")],
    "metadata": {"meeting_id": "m4_x", "meeting_date": "2026-08-27"},
    "document_id": "meeting-m4_x",
    "mentioned_at": "2026-08-27T00:00:00Z",
}
OBS_TAGGED = {
    "id": "o1",
    "text": "Budget is about 40K",
    "tags": [account_tag("acc_x"), meeting_tag("m2_x")],
    "metadata": {},
    "document_id": None,
    "mentioned_at": "2026-07-28T00:00:00Z",
}
OBS_MULTI = {
    "id": "o2",
    "text": "Rahul worries about data residency and security review",
    "tags": [meeting_tag("m1_x"), meeting_tag("m3_x")],
    "metadata": {},
    "document_id": None,
    "mentioned_at": "2026-08-12T00:00:00Z",
    "source_memory_ids": ["s1", "s2"],
}
SRC1 = {
    "id": "s1",
    "text": "Football match on Sunday",
    "tags": [meeting_tag("m1_x")],
    "metadata": {"meeting_id": "m1_x", "meeting_date": "2026-07-14"},
    "mentioned_at": "2026-07-14T00:00:00Z",
}
SRC2 = {
    "id": "s2",
    "text": "Rahul worries about data residency in the security review",
    "tags": [meeting_tag("m3_x")],
    "metadata": {"meeting_id": "m3_x", "meeting_date": "2026-08-12"},
    "mentioned_at": "2026-08-12T00:00:00Z",
}
OBS_NO_TAG = {
    "id": "o3",
    "text": "Something",
    "tags": [account_tag("acc_x")],
    "metadata": {},
    "mentioned_at": "2026-08-12T00:00:00Z",
    "source_memory_ids": ["gone"],
}


@pytest.mark.parametrize(
    ("memory_id", "meeting_id", "meeting_date"),
    [
        ("w1", "m4_x", date(2026, 8, 27)),  # world fact: metadata
        ("o1", "m2_x", date(2026, 7, 28)),  # observation: single meeting tag + mentioned_at
        ("o2", "m3_x", date(2026, 8, 12)),  # observation: several tags -> best-overlap source
        ("o3", None, None),  # unresolvable
        ("missing", None, None),  # 404
    ],
)
async def test_resolve_sources_cases(
    memory_id: str, meeting_id: str | None, meeting_date: date | None
) -> None:
    payloads = {p["id"]: p for p in (WORLD, OBS_TAGGED, OBS_MULTI, SRC1, SRC2, OBS_NO_TAG)}
    service, _ = _service(payloads)

    text = str(payloads.get(memory_id, {}).get("text", "x"))
    (out,) = await service.resolve_sources([_hit(memory_id, text)])

    assert out.meeting_id == meeting_id
    if meeting_id is not None:
        assert out.meeting_date == meeting_date
        assert out.tags  # tags filled from get_memory


async def test_observation_via_source_memories_ties_go_to_latest() -> None:
    obs = {**OBS_MULTI, "text": "unrelated wording zzz"}
    service, _ = _service({"o2": obs, "s1": SRC1, "s2": SRC2})

    (out,) = await service.resolve_sources([_hit("o2")])

    assert out.meeting_id == "m3_x"  # no overlap with either -> latest date


async def test_resolve_sources_uses_embedded_source_memories_without_extra_calls() -> None:
    obs = {**OBS_MULTI, "source_memories": [SRC1, SRC2]}
    service, api = _service({"o2": obs})

    (out,) = await service.resolve_sources([_hit("o2", OBS_MULTI["text"])])

    assert out.meeting_id == "m3_x"
    assert api.calls == ["o2"]


async def test_resolve_sources_caches_same_id_and_bounds_concurrency() -> None:
    payloads = {f"w{i}": {**WORLD, "id": f"w{i}"} for i in range(20)}
    service, api = _service(payloads)
    hits = [_hit("w0"), _hit("w0")] + [_hit(f"w{i}") for i in range(1, 20)]

    out = await service.resolve_sources(hits)

    assert len(out) == 21
    assert sorted(api.calls) == sorted(payloads)  # one call per unique id
    assert api.max_in_flight <= 8


async def test_resolve_sources_skips_already_resolved_hits() -> None:
    service, api = _service({})
    done = MemoryHit(
        memory_id="w1", text="t", meeting_id="m1", meeting_date=date(2026, 7, 14), tags=[]
    )

    (out,) = await service.resolve_sources([done])

    assert out == done
    assert api.calls == []


async def test_resolve_sources_maps_sdk_failure_to_memory_unavailable() -> None:
    service, _ = _service({})
    with pytest.raises(MemoryUnavailableError):
        await service.resolve_sources([_hit("boom")])


async def test_fake_resolve_sources_matches_real_rules() -> None:
    fake = FakeMemoryService()
    fake.seed_fact(
        "o1",
        "Budget is about 40K",
        tags=[account_tag("acc_x"), meeting_tag("m2_x")],
        memory_type="observation",
        mentioned_at=date(2026, 7, 28),
    )
    fake.seed_fact(
        "w1",
        "Deck",
        tags=[account_tag("acc_x"), meeting_tag("m4_x")],
        meeting_id="m4_x",
        meeting_date=date(2026, 8, 27),
    )

    out = await fake.resolve_sources([_hit("o1"), _hit("w1"), _hit("o1")])

    assert [(h.meeting_id, h.meeting_date) for h in out] == [
        ("m2_x", date(2026, 7, 28)),
        ("m4_x", date(2026, 8, 27)),
        ("m2_x", date(2026, 7, 28)),
    ]
    assert fake.get_memory_calls == ["o1", "w1"]


# -- recall observation fix ------------------------------------------------------


@dataclass
class _RecallStub:
    id: str
    text: str
    tags: list[str] | None
    metadata: dict[str, str] | None
    mentioned_at: datetime | None = None


def test_recall_observation_hit_gets_meeting_from_tag_and_mentioned_at() -> None:
    hit = _hit_from_recall_result(
        _RecallStub(
            id="o1",
            text="obs",
            tags=[account_tag("acc_x"), meeting_tag("m2_x")],
            metadata={},
            mentioned_at=datetime(2026, 7, 28, 0, 0),
        )
    )

    assert hit.meeting_id == "m2_x"
    assert hit.meeting_date == date(2026, 7, 28)


def test_recall_observation_with_several_meeting_tags_stays_unresolved() -> None:
    hit = _hit_from_recall_result(
        _RecallStub(
            id="o2", text="obs", tags=[meeting_tag("m1_x"), meeting_tag("m3_x")], metadata={}
        )
    )

    assert hit.meeting_id is None


def test_recall_world_hit_prefers_metadata() -> None:
    hit = _hit_from_recall_result(
        _RecallStub(
            id="w1",
            text="t",
            tags=[meeting_tag("m9_x")],
            metadata={"meeting_id": "m4_x", "meeting_date": "2026-08-27"},
            mentioned_at=datetime(2026, 1, 1),
        )
    )

    assert (hit.meeting_id, hit.meeting_date) == ("m4_x", date(2026, 8, 27))


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        (["account:a", "meeting:m1"], "m1"),
        (["meeting:m1", "meeting:m1"], "m1"),
        (["meeting:m1", "meeting:m2"], None),
        (["account:a"], None),
        ([], None),
    ],
)
def test_meeting_id_from_tags(tags: list[str], expected: str | None) -> None:
    assert meeting_id_from_tags(tags) == expected
