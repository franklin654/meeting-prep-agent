"""T12e: retain timeout override and consecutive-idle `wait_until_idle` on the real wrapper.

The Hindsight SDK client is replaced by small fakes; nothing touches the network and
nothing really sleeps (poll intervals are shrunk to ~0).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from app.core.errors import MemoryUnavailableError
from app.memory import memory_service as ms
from app.memory.memory_service import HindsightMemoryService, MemoryService
from tests.fakes.fake_memory_service import FakeMemoryService


class _SlowClient:
    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.calls = 0

    async def aretain(self, **kwargs: Any) -> None:
        self.calls += 1
        await asyncio.sleep(self.delay)


def _service(client: Any) -> HindsightMemoryService:
    return HindsightMemoryService(client=client)


async def _retain(service: MemoryService, **extra: Any) -> None:
    await service.retain_meeting(
        meeting_id="m1",
        account_id="acc",
        contact_ids=["c1"],
        meeting_date=date(2026, 9, 1),
        title="T",
        transcript="hello",
        **extra,
    )


def test_default_retain_timeout_is_30s() -> None:
    assert ms.RETAIN_TIMEOUT_S == 30.0


async def test_explicit_timeout_is_honoured_and_named_in_message() -> None:
    service = _service(_SlowClient(delay=1.0))
    with pytest.raises(MemoryUnavailableError, match=r"after 0\.05s"):
        await _retain(service, timeout_s=0.05)


async def test_longer_explicit_timeout_lets_a_slow_retain_finish() -> None:
    client = _SlowClient(delay=0.05)
    await _retain(_service(client), timeout_s=5.0)
    assert client.calls == 1


async def test_default_timeout_is_used_when_none_given(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ms, "RETAIN_TIMEOUT_S", 0.05)
    with pytest.raises(MemoryUnavailableError, match=r"after 0\.05s"):
        await _retain(_service(_SlowClient(delay=1.0)))


async def test_fake_records_retain_timeout() -> None:
    fake = FakeMemoryService()
    await _retain(fake, timeout_s=120.0)
    await _retain(fake)
    assert fake.retain_timeouts == [120.0, None]


async def test_structured_output_error_does_not_retry_reflect() -> None:
    class Output(BaseModel):
        answer: str

    class ReflectClient:
        def __init__(self) -> None:
            self.calls = 0

        async def areflect(self, **kwargs: Any) -> Any:
            self.calls += 1
            return SimpleNamespace(
                text="malformed",
                structured_output={"partial": "data"},
                structured_output_error="invalid shape",
                based_on=None,
            )

    client = ReflectClient()
    result = await _service(SimpleNamespace(areflect=client.areflect)).reflect_structured(
        query="q", tags=[], schema=Output
    )

    assert client.calls == 1
    assert result.structured is None
    assert result.structured_error == "invalid shape"


class _Ops:
    """`operations.list_operations` scripted by busy(False)/idle(True) poll results."""

    def __init__(self, script: Sequence[bool]) -> None:
        self.script = list(script)
        self.polls = 0

    async def list_operations(self, *, bank_id: str, status: str, limit: int) -> Any:
        # Two calls per poll (pending, processing); the script advances on "pending".
        if status == "pending":
            self.polls += 1
        idle = self.script[min(self.polls, len(self.script)) - 1]
        return SimpleNamespace(total=0 if idle or status == "processing" else 1)


def _idle_service(script: Sequence[bool]) -> tuple[HindsightMemoryService, _Ops]:
    ops = _Ops(script)
    return _service(SimpleNamespace(operations=ops)), ops


async def test_needs_three_consecutive_idle_polls() -> None:
    service, ops = _idle_service([True, True, False, True, True, True])
    assert await service.wait_until_idle(5.0, poll_interval_s=0.0) is True
    assert ops.polls == 6  # idle, idle, busy resets; then three in a row


async def test_gap_between_completed_and_requeued_operation_does_not_end_early() -> None:
    service, ops = _idle_service([True, False, True, True, True])
    assert await service.wait_until_idle(5.0, poll_interval_s=0.0) is True
    assert ops.polls == 5


async def test_timeout_returns_false_and_deadline_is_enforced() -> None:
    service, _ = _idle_service([False])
    assert await service.wait_until_idle(0.05, poll_interval_s=0.01) is False
    flapping, _ = _idle_service([True, True, False] * 200)
    assert await flapping.wait_until_idle(0.05, poll_interval_s=0.01) is False


async def test_final_sleep_is_clamped_to_the_remaining_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def recording_sleep(delay: float, *args: Any) -> None:
        sleeps.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(ms.asyncio, "sleep", recording_sleep)
    service, _ = _idle_service([False])
    assert await service.wait_until_idle(0.2, poll_interval_s=60.0) is False
    assert sleeps and max(sleeps) <= 0.2  # never a full 60 s poll interval


async def test_consecutive_idle_is_configurable() -> None:
    service, ops = _idle_service([True])
    assert await service.wait_until_idle(5.0, consecutive_idle=1, poll_interval_s=0.0) is True
    assert ops.polls == 1


async def test_fake_scripted_idle_polls() -> None:
    fake = FakeMemoryService()
    fake.idle_polls = [True, True, False, True, True, True]
    assert await fake.wait_until_idle() is True
    fake.idle_polls = [True, False, True, False]
    assert await fake.wait_until_idle() is False
