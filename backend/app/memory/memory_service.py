"""Hindsight gateway (docs/hindsight-integration.md "memory_service interface").

AGENTS.md hard rule 1: this is the only module that imports `hindsight_client`.
Every other module calls `MemoryService`, never the SDK directly.

SDK call shapes here were confirmed by installing `hindsight-client==0.10.1`
(pinned in `backend/pyproject.toml`) into this environment and introspecting
`hindsight_client.Hindsight`'s real method signatures with `inspect.signature`
and the generated `hindsight_client_api` response models with
`.model_fields` -- not guessed, and not solely the illustrative snippets in
the hindsight-docs skill / docs/data-model-and-schemas.md (see this module's
docstrings below and the ticket report for where the two disagreed).

Bootstrap order (docs/hindsight-integration.md "Bootstrap"):
    ensure_bank() -> retain (per meeting) -> wait_until_idle() -> ensure_mental_models()

Failure handling (docs/hindsight-integration.md "Failure handling"):
    - Unreachable / timeout (recall 5s, reflect 45s, retain 30s) -> `MemoryUnavailableError`.
    - Reflect HTTP 500 -> retry once after 2s, then `MemoryUnavailableError`.
    - `structured_output_error` present -> retry once; if it persists, the
      `ReflectResult` is returned with `structured=None` and `structured_error`
      set so the caller can drop that brief section (this module never drops
      sections itself -- it has no notion of "brief sections").
"""

from __future__ import annotations

import abc
import asyncio
import logging
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from hindsight_client import Hindsight
from hindsight_client_api.exceptions import ApiException, OpenApiException
from pydantic import BaseModel

from app.config import settings
from app.core.errors import MemoryUnavailableError
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

logger = logging.getLogger(__name__)

# docs/data-model-and-schemas.md "Hindsight model" -> "Bank config".
BANK_ID = f"ae-{settings.demo_user_id}"

BANK_CONFIG: dict[str, Any] = {
    "entity_labels": [
        {
            "key": "fact_kind",
            "type": "text",
            "tag": True,
            "description": (
                "What kind of sales-meeting fact this is. One of: commitment (a promise "
                "with an owner), objection (a concern or blocker), personal (life detail "
                "someone shared), deal_fact (budget, timeline, scope, stage, process), "
                "competitor (another vendor mentioned)."
            ),
        }
    ],
}

# docs/hindsight-integration.md "Failure handling".
RECALL_TIMEOUT_S = 5.0
REFLECT_TIMEOUT_S = 45.0
RETAIN_TIMEOUT_S = 30.0

# Reflect 500 retry delay, per "Failure handling": "Retry once after 2s".
REFLECT_RETRY_DELAY_S = 2.0

_STRUCTURED_OUTPUT_ERROR_MSG = "structured_output_error persisted after one retry"


class MentalModelText(BaseModel):
    """A mental model's curated content (docs/hindsight-integration.md's
    `get_mental_model(name) -> MentalModelText`).

    Not defined in docs/data-model-and-schemas.md or app/schemas/memory.py --
    only `MemoryHit`/`ReflectResult` are (see that module's docstring, which
    explicitly scopes `BANK_ID`/`BANK_CONFIG`/return types beyond those two to
    this ticket). Flagged in the ticket report as a doc gap worth closing.
    """

    id: str
    name: str
    content: str
    last_refreshed_at: datetime | None


class MemoryService(abc.ABC):
    """Interface shared by `HindsightMemoryService` and `FakeMemoryService`
    (tests/fakes/fake_memory_service.py), mirroring `app.llm.client.LLMClient`.
    """

    @abc.abstractmethod
    async def aclose(self) -> None:
        """Close the underlying client. Called once at app shutdown."""
        raise NotImplementedError

    @abc.abstractmethod
    async def ensure_bank(self) -> None:
        """Create/update the bank with `BANK_CONFIG`. Safe to call repeatedly."""
        raise NotImplementedError

    @abc.abstractmethod
    async def ensure_mental_models(self, accounts: Sequence[tuple[str, str]]) -> None:
        """Create the per-account relationship model and the user style model,
        skipping any that already exist. `accounts` is `(account_id, account_name)` pairs.
        """
        raise NotImplementedError

    @abc.abstractmethod
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
        """Retain one meeting transcript as a document with a stable id, so
        re-ingesting the same meeting replaces rather than duplicates it.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def retain_note(self, *, text: str, scope_type: ScopeType, scope_id: str) -> None:
        """Retain a user note (Ask panel's "Remember this"), tagged `kind:note`
        plus the scope tag for `scope_type`/`scope_id`.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def retain_preference(self, sentence: str) -> None:
        """Retain a short preference sentence tagged `kind:preference`, no account tag."""
        raise NotImplementedError

    @abc.abstractmethod
    async def recall_facts(
        self, *, query: str, tags: Sequence[str], fact_kind: FactKind | None = None
    ) -> list[MemoryHit]:
        """Recall matching facts. `fact_kind`, if given, is appended as a
        `fact_kind:<value>` tag. Fixed `tags_match="all_strict"`, `budget="mid"`
        per docs/hindsight-integration.md's Operation recipes table (see this
        module's `HindsightMemoryService.recall_facts` docstring for why that
        overrides the interface table's "any_strict" summary).
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def reflect_structured(
        self,
        *,
        query: str,
        tags: Sequence[str],
        schema: type[BaseModel],
        budget: str = "mid",
    ) -> ReflectResult:
        """Reflect with `response_schema=schema.model_json_schema()`,
        `include_facts=True`, fixed `tags_match="any_strict"`. `budget` is
        caller-supplied per the Operation recipes table (mid for most call
        sites, high for contradictions / cross-deal patterns).
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def get_mental_model(self, name: str) -> MentalModelText | None:
        """Read a mental model by its stable id. `None` if it doesn't exist."""
        raise NotImplementedError

    @abc.abstractmethod
    async def timeline(self, contact_id: str) -> list[MemoryHit]:
        """Recall everything tagged `contact:<id>`, `any_strict`, budget `low`,
        sorted by `meeting_date` (oldest first; `None` dates sort last).
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def wait_until_idle(self, timeout_s: float = 60.0) -> bool:
        """Poll until the bank has no pending/processing operations, or `timeout_s`
        elapses. Returns `True` if it went idle, `False` on timeout.
        """
        raise NotImplementedError


def _relationship_model_id(account_id: str) -> str:
    return f"relationship-{account_id}"


def _style_model_id() -> str:
    return f"style-{settings.demo_user_id}"


class HindsightMemoryService(MemoryService):
    """Real gateway to a running Hindsight server via `hindsight_client.Hindsight`."""

    def __init__(self, client: Hindsight | None = None) -> None:
        self._client = client or Hindsight(base_url=settings.hindsight_url)

    async def aclose(self) -> None:
        # `hindsight_client.Hindsight.aclose` ships with no type annotations
        # at all (confirmed via `inspect.signature`) -- a gap in the SDK's own
        # typing, not something to route around here.
        await self._client.aclose()  # type: ignore[no-untyped-call]

    async def ensure_bank(self) -> None:
        # `acreate_bank` is create-or-update (SDK method name: `create_or_update_bank`
        # on the underlying `banks` namespace) so this is safe to call on every
        # startup, per docs/hindsight-integration.md Bootstrap step 1.
        try:
            await self._client.acreate_bank(bank_id=BANK_ID)
            await self._client.aupdate_bank_config(
                BANK_ID, entity_labels=BANK_CONFIG["entity_labels"]
            )
        except (ApiException, OpenApiException, TimeoutError, OSError) as exc:
            raise MemoryUnavailableError(f"Could not ensure bank {BANK_ID!r}: {exc}") from exc

    async def ensure_mental_models(self, accounts: Sequence[tuple[str, str]]) -> None:
        try:
            existing = await self._client.alist_mental_models(bank_id=BANK_ID, detail="metadata")
            existing_ids = {item.id for item in (existing.items or [])}

            for account_id, account_name in accounts:
                model_id = _relationship_model_id(account_id)
                if model_id in existing_ids:
                    continue
                await self._client.acreate_mental_model(
                    bank_id=BANK_ID,
                    id=model_id,
                    name=f"Relationship: {account_name}",
                    source_query=(
                        f"What is the current state of our relationship with "
                        f"{account_name}: stage, key people, open issues?"
                    ),
                    tags=[account_tag(account_id)],
                )

            style_id = _style_model_id()
            if style_id not in existing_ids:
                await self._client.acreate_mental_model(
                    bank_id=BANK_ID,
                    id=style_id,
                    name="Brief style preferences",
                    source_query=(
                        "How does this user like their meeting briefs: length, "
                        "sections to emphasise or hide, tone?"
                    ),
                    tags=[kind_tag(MemoryKind.preference)],
                )
        except (ApiException, OpenApiException, TimeoutError, OSError) as exc:
            raise MemoryUnavailableError(f"Could not ensure mental models: {exc}") from exc

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

        await self._retain(
            content=transcript,
            document_id=f"meeting-{meeting_id}",
            tags=tags,
            metadata={
                "meeting_id": meeting_id,
                "meeting_date": meeting_date.isoformat(),
                "title": title,
                "source": source,
            },
            timestamp=datetime.combine(meeting_date, datetime.min.time()),
            context="sales meeting transcript",
        )

    async def retain_note(self, *, text: str, scope_type: ScopeType, scope_id: str) -> None:
        tags = [kind_tag(MemoryKind.note)]
        if scope_type == ScopeType.account:
            tags.append(account_tag(scope_id))
        elif scope_type == ScopeType.contact:
            tags.append(contact_tag(scope_id))
        elif scope_type == ScopeType.meeting:
            tags.append(meeting_tag(scope_id))

        await self._retain(content=text, tags=tags, context="user note")

    async def retain_preference(self, sentence: str) -> None:
        await self._retain(
            content=sentence,
            tags=[kind_tag(MemoryKind.preference)],
            context="brief feedback",
        )

    async def _retain(
        self,
        *,
        content: str,
        tags: list[str],
        context: str,
        document_id: str | None = None,
        metadata: dict[str, str] | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        try:
            async with asyncio.timeout(RETAIN_TIMEOUT_S):
                await self._client.aretain(
                    bank_id=BANK_ID,
                    content=content,
                    tags=tags,
                    context=context,
                    document_id=document_id,
                    metadata=metadata,
                    timestamp=timestamp,
                )
        except TimeoutError as exc:
            raise MemoryUnavailableError(
                f"Retain timed out after {RETAIN_TIMEOUT_S}s."
            ) from exc
        except (ApiException, OpenApiException, OSError) as exc:
            raise MemoryUnavailableError(f"Retain failed: {exc}") from exc

    async def recall_facts(
        self, *, query: str, tags: Sequence[str], fact_kind: FactKind | None = None
    ) -> list[MemoryHit]:
        full_tags = list(tags)
        if fact_kind is not None:
            full_tags.append(fact_kind_tag(fact_kind))

        try:
            async with asyncio.timeout(RECALL_TIMEOUT_S):
                response = await self._client.arecall(
                    bank_id=BANK_ID,
                    query=query,
                    tags=full_tags,
                    tags_match="all_strict",
                    budget="mid",
                    query_timestamp=_demo_today_iso(),
                )
        except TimeoutError as exc:
            raise MemoryUnavailableError(f"Recall timed out after {RECALL_TIMEOUT_S}s.") from exc
        except (ApiException, OpenApiException, OSError) as exc:
            raise MemoryUnavailableError(f"Recall failed: {exc}") from exc

        return [_hit_from_recall_result(r) for r in (response.results or [])]

    async def reflect_structured(
        self,
        *,
        query: str,
        tags: Sequence[str],
        schema: type[BaseModel],
        budget: str = "mid",
    ) -> ReflectResult:
        response_schema = schema.model_json_schema()

        response = await self._reflect_once(
            query=query, tags=tags, budget=budget, response_schema=response_schema
        )

        if response.structured_output_error:
            logger.warning(
                "memory.reflect.structured_output_error attempt=0 schema=%s error=%s",
                schema.__name__,
                response.structured_output_error,
            )
            response = await self._reflect_once(
                query=query, tags=tags, budget=budget, response_schema=response_schema
            )
            if response.structured_output_error:
                logger.warning(
                    "memory.reflect.structured_output_error attempt=1 schema=%s error=%s -- "
                    "dropping structured output",
                    schema.__name__,
                    response.structured_output_error,
                )

        return ReflectResult(
            text=response.text or "",
            structured=response.structured_output,
            sources=[_hit_from_reflect_fact(f) for f in (response.based_on.memories or [])]
            if response.based_on
            else [],
            structured_error=response.structured_output_error,
        )

    async def _reflect_once(
        self,
        *,
        query: str,
        tags: Sequence[str],
        budget: str,
        response_schema: dict[str, Any],
    ) -> Any:
        for attempt in range(2):  # original call + exactly one retry on HTTP 500
            try:
                async with asyncio.timeout(REFLECT_TIMEOUT_S):
                    return await self._client.areflect(
                        bank_id=BANK_ID,
                        query=query,
                        tags=list(tags),
                        tags_match="any_strict",
                        budget=budget,
                        response_schema=response_schema,
                        include_facts=True,
                    )
            except TimeoutError as exc:
                raise MemoryUnavailableError(
                    f"Reflect timed out after {REFLECT_TIMEOUT_S}s."
                ) from exc
            except ApiException as exc:
                if exc.status == 500 and attempt == 0:
                    logger.warning(
                        "memory.reflect.http_500 retrying_after=%.1fs", REFLECT_RETRY_DELAY_S
                    )
                    await asyncio.sleep(REFLECT_RETRY_DELAY_S)
                    continue
                raise MemoryUnavailableError(f"Reflect failed: {exc}") from exc
            except (OpenApiException, OSError) as exc:
                raise MemoryUnavailableError(f"Reflect failed: {exc}") from exc
        raise AssertionError("unreachable")  # pragma: no cover

    async def get_mental_model(self, name: str) -> MentalModelText | None:
        try:
            model = await self._client.aget_mental_model(
                bank_id=BANK_ID, mental_model_id=name, detail="content"
            )
        except ApiException as exc:
            if exc.status == 404:
                return None
            raise MemoryUnavailableError(f"Could not read mental model {name!r}: {exc}") from exc
        except (OpenApiException, OSError) as exc:
            raise MemoryUnavailableError(f"Could not read mental model {name!r}: {exc}") from exc

        return MentalModelText(
            id=model.id,
            name=model.name,
            content=model.content or "",
            last_refreshed_at=model.last_refreshed_at,
        )

    async def timeline(self, contact_id: str) -> list[MemoryHit]:
        try:
            async with asyncio.timeout(RECALL_TIMEOUT_S):
                response = await self._client.arecall(
                    bank_id=BANK_ID,
                    query=f"Everything involving {contact_id}",
                    tags=[contact_tag(contact_id)],
                    tags_match="any_strict",
                    budget="low",
                    query_timestamp=_demo_today_iso(),
                )
        except TimeoutError as exc:
            raise MemoryUnavailableError(
                f"Timeline recall timed out after {RECALL_TIMEOUT_S}s."
            ) from exc
        except (ApiException, OpenApiException, OSError) as exc:
            raise MemoryUnavailableError(f"Timeline recall failed: {exc}") from exc

        hits = [_hit_from_recall_result(r) for r in (response.results or [])]
        return sorted(hits, key=lambda h: h.meeting_date or date.min)

    async def wait_until_idle(self, timeout_s: float = 60.0) -> bool:
        deadline = asyncio.get_event_loop().time() + timeout_s
        while True:
            try:
                pending = await self._client.operations.list_operations(
                    bank_id=BANK_ID, status="pending", limit=1
                )
                processing = await self._client.operations.list_operations(
                    bank_id=BANK_ID, status="processing", limit=1
                )
            except (ApiException, OpenApiException, OSError) as exc:
                raise MemoryUnavailableError(f"Could not poll bank operations: {exc}") from exc

            if pending.total == 0 and processing.total == 0:
                return True
            if asyncio.get_event_loop().time() >= deadline:
                return False
            await asyncio.sleep(1.0)


def _demo_today_iso() -> str:
    return datetime.combine(settings.demo_today, datetime.min.time()).isoformat()


def _hit_from_recall_result(result: Any) -> MemoryHit:
    metadata = result.metadata or {}
    meeting_date_str = metadata.get("meeting_date")
    meeting_date = date.fromisoformat(meeting_date_str) if meeting_date_str else None
    return MemoryHit(
        memory_id=result.id,
        text=result.text,
        meeting_id=metadata.get("meeting_id"),
        meeting_date=meeting_date,
        tags=list(result.tags or []),
    )


def _hit_from_reflect_fact(fact: Any) -> MemoryHit:
    # `ReflectFact` (from `based_on.memories`) only carries id/text/type/context/
    # occurred_start/occurred_end -- no tags or metadata, unlike `RecallResult`.
    # So `meeting_id` and `tags` can't be recovered here; `meeting_date` falls
    # back to `occurred_start`'s date. Noted as a doc gap in the ticket report.
    meeting_date = fact.occurred_start.date() if fact.occurred_start else None
    return MemoryHit(
        memory_id=fact.id,
        text=fact.text,
        meeting_id=None,
        meeting_date=meeting_date,
        tags=[],
    )
