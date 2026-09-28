"""Hindsight tag vocabulary (docs/data-model-and-schemas.md "Hindsight model" ->
"Tag vocabulary" table).

AGENTS.md hard rule 2: tags are only ever built through this module. Nothing
else in the codebase types a `"account:..."` / `"kind:..."` string by hand.

| Tag | Written when |
| --- | --- |
| `account:<id>` | Every transcript and note for an account |
| `contact:<id>` | Once per attendee on a transcript; on contact-scoped notes |
| `meeting:<id>` | Every transcript; meeting-scoped notes |
| `kind:transcript` \\| `kind:note` \\| `kind:preference` | Every retain |
| `fact_kind:<value>` | Automatically, by the `fact_kind` entity label (BANK_CONFIG) |
"""

from __future__ import annotations

from enum import StrEnum

from app.schemas.enums import FactKind


class MemoryKind(StrEnum):
    """The `kind:<value>` tag values written on every retain.

    Not one of the shared enums in `app/schemas/enums.py` (those are
    API/DB/prompt-facing per that module's docstring); this one only feeds
    tag strings, so it lives with the tag builders.
    """

    transcript = "transcript"
    note = "note"
    preference = "preference"


def account_tag(account_id: str) -> str:
    return f"account:{account_id}"


def contact_tag(contact_id: str) -> str:
    return f"contact:{contact_id}"


def meeting_tag(meeting_id: str) -> str:
    return f"meeting:{meeting_id}"


def kind_tag(kind: MemoryKind) -> str:
    return f"kind:{kind.value}"


def fact_kind_tag(fact_kind: FactKind) -> str:
    return f"fact_kind:{fact_kind.value}"
