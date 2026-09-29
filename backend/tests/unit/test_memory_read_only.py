"""Read-only Hindsight guards never invoke a client write method."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.memory.memory_service as memory_module
from app.config import Settings
from app.core.errors import MemoryReadOnlyError
from app.memory.memory_service import HindsightMemoryService
from app.schemas.enums import ScopeType


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> tuple[HindsightMemoryService, MagicMock]:
    config = Settings(_env_file=None, memory_read_only=True)  # type: ignore[call-arg]
    monkeypatch.setattr(memory_module, "settings", config)
    client = MagicMock()
    client.acreate_bank = AsyncMock()
    client.aupdate_bank_config = AsyncMock()
    client.alist_mental_models = AsyncMock()
    client.acreate_mental_model = AsyncMock()
    client.aretain = AsyncMock()
    return HindsightMemoryService(client=client), client


@pytest.mark.parametrize(
    "operation",
    ["ensure_bank", "ensure_mental_models", "retain_meeting", "retain_note", "retain_preference"],
)
async def test_read_only_blocks_all_hindsight_writes(
    service: tuple[HindsightMemoryService, MagicMock], operation: str
) -> None:
    memory, client = service

    with pytest.raises(MemoryReadOnlyError, match="MEMORY_READ_ONLY"):
        if operation == "ensure_bank":
            await memory.ensure_bank()
        elif operation == "ensure_mental_models":
            await memory.ensure_mental_models([("acc_finedge", "FinEdge")])
        elif operation == "retain_meeting":
            await memory.retain_meeting(
                meeting_id="m1", account_id="acc_finedge", contact_ids=[],
                meeting_date=date(2026, 9, 1), title="Test", transcript="Transcript"
            )
        elif operation == "retain_note":
            await memory.retain_note(
                text="note", scope_type=ScopeType.account, scope_id="acc_finedge"
            )
        else:
            await memory.retain_preference("short briefs")

    client.acreate_bank.assert_not_awaited()
    client.aupdate_bank_config.assert_not_awaited()
    client.acreate_mental_model.assert_not_awaited()
    client.aretain.assert_not_awaited()
