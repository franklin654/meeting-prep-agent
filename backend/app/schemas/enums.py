"""Shared `StrEnum`s from docs/data-model-and-schemas.md ("Conventions").

Values are lowercase snake_case and shared by API, DB and prompts. Per that
doc's "Change rules": enum values are never renamed once seeded; add new
values instead.
"""

from __future__ import annotations

from enum import StrEnum


class FactKind(StrEnum):
    commitment = "commitment"
    objection = "objection"
    personal = "personal"
    deal_fact = "deal_fact"
    competitor = "competitor"


class Owner(StrEnum):
    us = "us"
    them = "them"


class CommitmentStatus(StrEnum):
    open = "open"
    done = "done"


class ScopeType(StrEnum):
    account = "account"
    contact = "contact"
    meeting = "meeting"
