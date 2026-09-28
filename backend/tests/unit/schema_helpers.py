"""Shared test helper for T05 schema round-trip tests.

Not a `test_*` module itself, so pytest does not collect it directly.
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


def round_trip(model: ModelT) -> None:
    """Assert `model` survives `model_dump(mode="json")` -> `model_validate`."""
    dumped = model.model_dump(mode="json")
    restored = type(model).model_validate(dumped)
    assert restored == model
