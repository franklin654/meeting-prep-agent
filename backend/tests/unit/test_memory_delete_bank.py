"""`delete_bank` hard guard and behaviour (real service with a mocked SDK client,
plus the fake). No network."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from hindsight_client_api.exceptions import ApiException

from app.core.errors import MemoryUnavailableError, ValidationError
from app.memory.memory_service import HindsightMemoryService
from app.schemas.enums import ScopeType
from tests.fakes.fake_memory_service import FakeMemoryService

REFUSED = ["ami-test", "spike-abc", "", "ae-", "AE-x", " ae-x", "ae-x ", "xae-x", "spike-ae-x"]
REFUSED += ["ae-a b", "ae-x\ny", "ae-x\n", "ae-../x", "ae-x/y", "ae-x\\y", "ae-x.y", "ae- x"]
ACCEPTED = ["ae-priya", "ae-user-demo-thomas"]


def _service() -> tuple[HindsightMemoryService, MagicMock]:
    client = MagicMock()
    client.adelete_bank = AsyncMock(return_value=None)
    return HindsightMemoryService(client=client), client


@pytest.mark.parametrize("bank_id", REFUSED)
async def test_real_refuses_non_ae_ids_without_sdk_call(bank_id: str) -> None:
    service, client = _service()
    with pytest.raises(ValidationError):
        await service.delete_bank(bank_id)
    client.adelete_bank.assert_not_called()
    assert client.method_calls == []


@pytest.mark.parametrize("bank_id", ACCEPTED)
async def test_real_accepts_ae_ids_with_exactly_one_call(bank_id: str) -> None:
    service, client = _service()
    await service.delete_bank(bank_id)
    client.adelete_bank.assert_awaited_once_with(bank_id)
    assert len(client.method_calls) == 1


async def test_real_404_is_success() -> None:
    service, client = _service()
    client.adelete_bank.side_effect = ApiException(status=404, reason="Not Found")
    await service.delete_bank("ae-gone")
    client.adelete_bank.assert_awaited_once_with("ae-gone")


@pytest.mark.parametrize(
    "error", [ApiException(status=500, reason="boom"), OSError("down"), TimeoutError()]
)
async def test_real_other_errors_map_to_memory_unavailable(error: Exception) -> None:
    service, client = _service()
    client.adelete_bank.side_effect = error
    with pytest.raises(MemoryUnavailableError):
        await service.delete_bank("ae-priya")


@pytest.mark.parametrize("bank_id", REFUSED)
async def test_fake_refuses_non_ae_ids(bank_id: str) -> None:
    fake = FakeMemoryService()
    await fake.retain_note(text="keep me", scope_type=ScopeType.account, scope_id="acc_x")
    with pytest.raises(ValidationError):
        await fake.delete_bank(bank_id)
    assert len(fake.items) == 1


@pytest.mark.parametrize("bank_id", ACCEPTED)
async def test_fake_accepts_ae_ids_and_clears_state(bank_id: str) -> None:
    fake = FakeMemoryService()
    await fake.ensure_bank()
    await fake.retain_note(text="x", scope_type=ScopeType.account, scope_id="acc_x")
    await fake.delete_bank(bank_id)
    assert fake.items == []
    assert fake.mental_models == {}
    assert fake.bank_ensured is False
    assert fake.deleted_banks == [bank_id]
