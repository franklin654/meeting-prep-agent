"""In-memory `MemoryService` double for unit tests. No network calls, ever.

docs/hindsight-integration.md "Testing": "`FakeMemoryService`: same interface;
stores retained items in memory; `recall_facts` filters by tags and simple
keyword match; `reflect_structured` returns canned `ReflectResult`s registered
per test." Mirrors `FakeLLM`'s queue-and-record pattern (tests/fakes/fake_llm.py)
for consistency.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel

from app.memory.memory_service import (
    MemoryService,
    MentalModelText,
    meeting_fields,
    require_deletable_bank_id,
    resolve_hit_from_payload,
)
from app.memory.tags import (
    MemoryKind,
    account_tag,
    contact_tag,
    fact_kind_tag,
    kind_tag,
    meeting_tag,
)
from app.schemas.enums import FactKind, ScopeType
from app.schemas.memory import MemoryHit, ReflectResult


@dataclass
class _RetainedItem:
    memory_id: str
    text: str
    tags: list[str]
    meeting_id: str | None = None
    meeting_date: date | None = None
    document_id: str | None = None
    title: str | None = None
    source: str | None = None
    # Fidelity for Hindsight's `world` vs `observation` facts (see `seed_fact`).
    memory_type: str = "world"
    metadata: dict[str, str] | None = None
    mentioned_at: date | None = None
    source_memory_ids: list[str] | None = None


class FakeMemoryService(MemoryService):
    """Stores retained items in memory; canned reflect responses are queued
    per test and handed back in FIFO order (`queue_reflect_response`).
    """

    def __init__(self) -> None:
        self.items: list[_RetainedItem] = []
        self.mental_models: dict[str, MentalModelText] = {}
        self._reflect_queue: list[ReflectResult | Exception] = []
        self.reflect_calls: list[tuple[str, list[str], str]] = []
        self.closed = False
        self.deleted_banks: list[str] = []
        self.bank_ensured = False
        self._next_id = 0
        self.get_memory_calls: list[str] = []

    # -- test helpers ---------------------------------------------------

    def queue_reflect_response(self, response: ReflectResult) -> None:
        self._reflect_queue.append(response)

    def queue_reflect_error(self, error: Exception) -> None:
        self._reflect_queue.append(error)

    def seed_mental_model(self, model_id: str, *, name: str, content: str) -> None:
        self.mental_models[model_id] = MentalModelText(
            id=model_id, name=name, content=content, last_refreshed_at=None
        )

    def seed_fact(
        self,
        memory_id: str,
        text: str,
        *,
        tags: Sequence[str],
        meeting_id: str | None = None,
        meeting_date: date | None = None,
        memory_type: str = "world",
        mentioned_at: date | None = None,
        source_memory_ids: Sequence[str] | None = None,
    ) -> None:
        """Add one extracted fact the way Hindsight stores it.

        `world` facts carry `meeting_id` / `meeting_date` in metadata and a
        `meeting-<id>` document id. `observation` facts have EMPTY metadata and no
        document id (their meeting shows only in `meeting:` tags / `mentioned_at`).
        """
        world = memory_type == "world"
        metadata: dict[str, str] = {}
        if world and meeting_id:
            metadata["meeting_id"] = meeting_id
        if world and meeting_date:
            metadata["meeting_date"] = meeting_date.isoformat()
        self.items.append(
            _RetainedItem(
                memory_id=memory_id,
                text=text,
                tags=list(tags),
                document_id=f"meeting-{meeting_id}" if world and meeting_id else None,
                memory_type=memory_type,
                metadata=metadata,
                mentioned_at=mentioned_at or meeting_date,
                source_memory_ids=list(source_memory_ids) if source_memory_ids else None,
            )
        )

    def _new_id(self) -> str:
        self._next_id += 1
        return f"fake-mem-{self._next_id}"

    # -- MemoryService ----------------------------------------------------

    async def aclose(self) -> None:
        self.closed = True

    async def ensure_bank(self) -> None:
        self.bank_ensured = True

    async def ensure_mental_models(self, accounts: Sequence[tuple[str, str]]) -> None:
        for account_id, account_name in accounts:
            model_id = f"relationship-{account_id}"
            if model_id not in self.mental_models:
                self.seed_mental_model(
                    model_id,
                    name=f"Relationship: {account_name}",
                    content="",
                )
        if "style-fake-user" not in self.mental_models:
            self.seed_mental_model("style-fake-user", name="Brief style preferences", content="")

    async def retain_meeting(
        self,
        *,
        meeting_id: str,
        account_id: str,
        contact_ids: Sequence[str],
        meeting_date: date,
        title: str,
        transcript: str,
        source: str = "ingest",
    ) -> None:
        tags = [account_tag(account_id)]
        tags.extend(contact_tag(cid) for cid in contact_ids)
        tags.append(meeting_tag(meeting_id))
        tags.append(kind_tag(MemoryKind.transcript))
        document_id = f"meeting-{meeting_id}"
        # Same document id replaces the earlier retain, as Hindsight does.
        self.items = [i for i in self.items if i.document_id != document_id]
        self.items.append(
            _RetainedItem(
                memory_id=document_id,
                text=transcript,
                tags=tags,
                meeting_id=meeting_id,
                meeting_date=meeting_date,
                document_id=document_id,
                title=title,
                source=source,
            )
        )

    async def retain_note(self, *, text: str, scope_type: ScopeType, scope_id: str) -> None:
        tags = [kind_tag(MemoryKind.note)]
        if scope_type == ScopeType.account:
            tags.append(account_tag(scope_id))
        elif scope_type == ScopeType.contact:
            tags.append(contact_tag(scope_id))
        elif scope_type == ScopeType.meeting:
            tags.append(meeting_tag(scope_id))
        self.items.append(_RetainedItem(memory_id=self._new_id(), text=text, tags=tags))

    async def retain_preference(self, sentence: str) -> None:
        self.items.append(
            _RetainedItem(
                memory_id=self._new_id(), text=sentence, tags=[kind_tag(MemoryKind.preference)]
            )
        )

    async def recall_facts(
        self, *, query: str, tags: Sequence[str], fact_kind: FactKind | None = None
    ) -> list[MemoryHit]:
        full_tags = list(tags)
        if fact_kind is not None:
            full_tags.append(fact_kind_tag(fact_kind))
        matches = [item for item in self.items if _all_strict(item.tags, full_tags)]
        matches = [item for item in matches if _keyword_match(query, item.text)]
        return [_to_hit(item) for item in matches]

    async def reflect_structured(
        self,
        *,
        query: str,
        tags: Sequence[str],
        schema: type[BaseModel],
        budget: str = "mid",
    ) -> ReflectResult:
        self.reflect_calls.append((query, list(tags), budget))
        if not self._reflect_queue:
            raise AssertionError(
                "FakeMemoryService.reflect_structured called with no canned response "
                "queued. Call queue_reflect_response()/queue_reflect_error() in the test first."
            )
        item = self._reflect_queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def get_mental_model(self, name: str) -> MentalModelText | None:
        return self.mental_models.get(name)

    async def timeline(self, contact_id: str) -> list[MemoryHit]:
        tag = contact_tag(contact_id)
        matches = [item for item in self.items if tag in item.tags]
        hits = [_to_hit(item) for item in matches]
        return sorted(hits, key=lambda h: h.meeting_date or date.min)

    async def resolve_sources(self, hits: Sequence[MemoryHit]) -> list[MemoryHit]:
        """Same resolution rules as `HindsightMemoryService`, over the fake's own store."""
        cache: dict[str, dict[str, Any] | None] = {}

        async def fetch(memory_id: str) -> dict[str, Any] | None:
            if memory_id not in cache:
                self.get_memory_calls.append(memory_id)
                cache[memory_id] = self._payload(memory_id)
            return cache[memory_id]

        resolved: list[MemoryHit] = []
        for hit in hits:
            if hit.meeting_id is not None and hit.meeting_date is not None:
                resolved.append(hit)
                continue
            payload = await fetch(hit.memory_id)
            if payload is None:
                resolved.append(hit)
            else:
                resolved.append(await resolve_hit_from_payload(hit, payload, fetch))
        return resolved

    def _payload(self, memory_id: str) -> dict[str, Any] | None:
        for item in self.items:
            if item.memory_id == memory_id:
                return {
                    "id": item.memory_id,
                    "text": item.text,
                    "tags": list(item.tags),
                    "metadata": dict(item.metadata or {}),
                    "mentioned_at": item.mentioned_at,
                    "document_id": item.document_id,
                    "source_memory_ids": item.source_memory_ids or [],
                }
        return None

    async def wait_until_idle(self, timeout_s: float = 60.0) -> bool:
        return True

    async def delete_bank(self, bank_id: str) -> None:
        require_deletable_bank_id(bank_id)
        self.items = []
        self.mental_models = {}
        self.bank_ensured = False
        self.deleted_banks.append(bank_id)


def _all_strict(item_tags: list[str], required_tags: list[str]) -> bool:
    return all(tag in item_tags for tag in required_tags)


def _keyword_match(query: str, text: str) -> bool:
    words = [w for w in query.lower().split() if w]
    if not words:
        return True
    text_lower = text.lower()
    return any(word in text_lower for word in words)


def _to_hit(item: _RetainedItem) -> MemoryHit:
    if item.metadata is not None:
        # Seeded fact: map exactly as the real recall mapping does.
        meeting_id, meeting_date = meeting_fields(
            metadata=item.metadata, tags=item.tags, mentioned_at=item.mentioned_at
        )
        return MemoryHit(
            memory_id=item.memory_id,
            text=item.text,
            meeting_id=meeting_id,
            meeting_date=meeting_date,
            tags=item.tags,
        )
    return MemoryHit(
        memory_id=item.memory_id,
        text=item.text,
        meeting_id=item.meeting_id,
        meeting_date=item.meeting_date,
        tags=item.tags,
    )
