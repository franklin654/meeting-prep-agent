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

from collections.abc import Sequence
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


_MEETING_TAG_PREFIX = meeting_tag("")
_FACT_KIND_PREFIX = "fact_kind:"


def fact_kind_from_tags(tags: Sequence[str]) -> FactKind | None:
    """The `FactKind` in a `fact_kind:<value>` tag, or None when absent or unknown."""
    for tag in tags:
        if tag.startswith(_FACT_KIND_PREFIX):
            try:
                return FactKind(tag[len(_FACT_KIND_PREFIX) :])
            except ValueError:
                continue
    return None


def meeting_ids_from_tags(tags: Sequence[str]) -> list[str]:
    """Every meeting id carried by `meeting:<id>` tags, in order, without duplicates."""
    found: list[str] = []
    for tag in tags:
        if tag.startswith(_MEETING_TAG_PREFIX):
            meeting_id = tag[len(_MEETING_TAG_PREFIX) :]
            if meeting_id and meeting_id not in found:
                found.append(meeting_id)
    return found


def meeting_id_from_tags(tags: Sequence[str]) -> str | None:
    """The meeting id when `tags` carry exactly one `meeting:<id>` tag, else None.

    Zero tags mean unknown; several mean a consolidated observation spanning
    meetings, which the caller must resolve through its source memories.
    """
    ids = meeting_ids_from_tags(tags)
    return ids[0] if len(ids) == 1 else None
