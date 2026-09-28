"""Round-trip and value tests for the shared StrEnums (T05).

docs/data-model-and-schemas.md "Conventions": enum values are lowercase
snake_case, shared by API, DB and prompts.
"""

from __future__ import annotations

from app.schemas.enums import CommitmentStatus, FactKind, Owner, ScopeType


def test_fact_kind_values() -> None:
    assert {member.value for member in FactKind} == {
        "commitment",
        "objection",
        "personal",
        "deal_fact",
        "competitor",
    }


def test_owner_values() -> None:
    assert {member.value for member in Owner} == {"us", "them"}


def test_commitment_status_values() -> None:
    assert {member.value for member in CommitmentStatus} == {"open", "done"}


def test_scope_type_values() -> None:
    assert {member.value for member in ScopeType} == {"account", "contact", "meeting"}


def test_enum_values_are_lowercase_snake_case() -> None:
    for enum_cls in (FactKind, Owner, CommitmentStatus, ScopeType):
        for member in enum_cls:
            assert member.value == member.value.lower()
            assert " " not in member.value
