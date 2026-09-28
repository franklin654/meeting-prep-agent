"""Tag builders (docs/data-model-and-schemas.md "Hindsight model" -> "Tag vocabulary")."""

from __future__ import annotations

from app.memory.tags import (
    MemoryKind,
    account_tag,
    contact_tag,
    fact_kind_tag,
    kind_tag,
    meeting_tag,
)
from app.schemas.enums import FactKind


def test_account_tag() -> None:
    assert account_tag("acc_finedge") == "account:acc_finedge"


def test_contact_tag() -> None:
    assert contact_tag("c_anita") == "contact:c_anita"


def test_meeting_tag() -> None:
    assert meeting_tag("m4_finedge") == "meeting:m4_finedge"


def test_kind_tag_covers_every_memory_kind() -> None:
    assert kind_tag(MemoryKind.transcript) == "kind:transcript"
    assert kind_tag(MemoryKind.note) == "kind:note"
    assert kind_tag(MemoryKind.preference) == "kind:preference"


def test_fact_kind_tag_covers_every_fact_kind() -> None:
    for value in FactKind:
        assert fact_kind_tag(value) == f"fact_kind:{value.value}"
