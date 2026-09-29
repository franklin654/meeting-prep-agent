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
    - `structured_output_error` present -> return it with empty structured output;
      validation failures are logged and dropped by the stage parser without retry.
"""

from __future__ import annotations

import abc
import asyncio
import logging
import re
import time
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from hindsight_client import Hindsight
from hindsight_client_api.exceptions import ApiException, OpenApiException
from pydantic import BaseModel

from app.config import settings
from app.core.errors import MemoryUnavailableError, ValidationError
from app.memory.tags import (
    MemoryKind,
    account_tag,
    contact_tag,
    fact_kind_tag,
    kind_tag,
    meeting_id_from_tags,
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
GET_MEMORY_TIMEOUT_S = 5.0
# Concurrent `get_memory` calls per `resolve_sources` batch.
RESOLVE_CONCURRENCY = 8

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
        timeout_s: float | None = None,
    ) -> None:
        """Retain one meeting transcript as a document with a stable id, so
        re-ingesting the same meeting replaces rather than duplicates it.

        `timeout_s` overrides the client-side retain limit (`RETAIN_TIMEOUT_S`, 30 s) for
        this call only; `None` keeps the default.
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
    async def resolve_sources(self, hits: Sequence[MemoryHit]) -> list[MemoryHit]:
        """Fill `meeting_id`, `meeting_date` and `tags` on hits (typically reflect
        sources, which carry none of them) so they can be cited.

        One `get_memory` per unique memory id, concurrently, cached for the call.
        A hit that cannot be resolved is returned with `meeting_id=None`; the
        caller drops it. See `HindsightMemoryService.resolve_sources` for rules.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def wait_until_idle(
        self,
        timeout_s: float = 60.0,
        *,
        consecutive_idle: int = 3,
        poll_interval_s: float = 5.0,
    ) -> bool:
        """Poll until the bank has had no pending/processing operations for
        `consecutive_idle` polls in a row (`poll_interval_s` apart; a busy poll resets the
        count, so the gap before a re-queued consolidation task does not end the wait early),
        or `timeout_s` elapses. Returns `True` if it went idle, `False` on timeout.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def delete_bank(self, bank_id: str) -> None:
        """Delete exactly the named bank. HARD GUARD: only ids starting with
        `ae-` (with at least one more character) are accepted; anything else
        raises `ValidationError` before any SDK call. An absent bank is success.
        """
        raise NotImplementedError


DELETABLE_BANK_PREFIX = "ae-"
_DELETABLE_BANK_RE = re.compile(r"^ae-[A-Za-z0-9_-]+$")


def require_deletable_bank_id(bank_id: str) -> None:
    """Hard guard for `delete_bank`: only `ae-<name>` ids may be deleted.

    The whole id must match `^ae-[A-Za-z0-9_-]+$` (no whitespace, newline or path
    characters anywhere). Raises `ValidationError` before any SDK call for anything else
    (including "", "ae-" alone, "AE-x", "ami-test", "spike-*", "ae-a b", "ae-../x").
    """
    # `fullmatch` so a trailing newline can never slip past `$`.
    if _DELETABLE_BANK_RE.fullmatch(bank_id) is None:
        raise ValidationError(
            f"Refusing to delete bank {bank_id!r}: only ids matching "
            f"{_DELETABLE_BANK_RE.pattern!r} may be deleted."
        )


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
        timeout_s: float | None = None,
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
            timeout_s=timeout_s,
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
        timeout_s: float | None = None,
    ) -> None:
        limit = RETAIN_TIMEOUT_S if timeout_s is None else timeout_s
        try:
            async with asyncio.timeout(limit):
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
            raise MemoryUnavailableError(f"Retain timed out after {limit:g}s.") from exc
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

        return ReflectResult(
            text=response.text or "",
            structured=None if response.structured_output_error else response.structured_output,
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
                        "memory.reflect.http_500 retrying_after=%.1fs attempt=%d",
                        REFLECT_RETRY_DELAY_S,
                        attempt + 1,
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

    async def resolve_sources(self, hits: Sequence[MemoryHit]) -> list[MemoryHit]:
        """Resolve each hit's meeting via `client.memory.get_memory` (docs/hindsight-integration.md
        "Mapping a memory to its meeting"). Hits that already have both `meeting_id` and
        `meeting_date` are passed through without a call.

        Observations with zero or several `meeting:` tags are resolved one level down through
        their source memories (see `choose_meeting_from_sources`).
        """
        started = time.monotonic()
        semaphore = asyncio.Semaphore(RESOLVE_CONCURRENCY)
        cache: dict[str, asyncio.Future[dict[str, Any] | None]] = {}
        calls = 0

        def fetch(memory_id: str) -> asyncio.Future[dict[str, Any] | None]:
            nonlocal calls
            if memory_id not in cache:
                calls += 1
                cache[memory_id] = asyncio.ensure_future(self._get_memory(memory_id, semaphore))
            return cache[memory_id]

        async def resolve(hit: MemoryHit) -> MemoryHit:
            if hit.meeting_id is not None and hit.meeting_date is not None:
                return hit
            payload = await fetch(hit.memory_id)
            if payload is None:
                return hit
            return await resolve_hit_from_payload(hit, payload, fetch)

        try:
            return list(await asyncio.gather(*(resolve(h) for h in hits)))
        finally:
            for future in cache.values():
                if not future.done():
                    future.cancel()
            logger.info(
                "memory.resolve_sources hits=%d get_memory_calls=%d duration_ms=%d",
                len(hits),
                calls,
                int((time.monotonic() - started) * 1000),
            )

    async def _get_memory(
        self, memory_id: str, semaphore: asyncio.Semaphore
    ) -> dict[str, Any] | None:
        async with semaphore:
            try:
                async with asyncio.timeout(GET_MEMORY_TIMEOUT_S):
                    raw = await self._client.memory.get_memory(BANK_ID, memory_id)
            except TimeoutError as exc:
                raise MemoryUnavailableError(
                    f"get_memory timed out after {GET_MEMORY_TIMEOUT_S}s."
                ) from exc
            except ApiException as exc:
                if exc.status == 404:
                    return None
                raise MemoryUnavailableError(f"get_memory failed: {exc}") from exc
            except (OpenApiException, OSError) as exc:
                raise MemoryUnavailableError(f"get_memory failed: {exc}") from exc
        return _as_dict(raw)

    async def wait_until_idle(
        self,
        timeout_s: float = 60.0,
        *,
        consecutive_idle: int = 3,
        poll_interval_s: float = 5.0,
    ) -> bool:
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout_s
        idle_polls = 0
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

            idle_polls = idle_polls + 1 if pending.total == 0 and processing.total == 0 else 0
            if idle_polls >= max(1, consecutive_idle):
                return True
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False
            # Never sleep past the deadline: the total stays within `timeout_s`.
            await asyncio.sleep(min(poll_interval_s, remaining))

    async def delete_bank(self, bank_id: str) -> None:
        require_deletable_bank_id(bank_id)
        started = time.monotonic()
        try:
            await self._client.adelete_bank(bank_id)
        except ApiException as exc:
            if exc.status != 404:
                raise MemoryUnavailableError(f"Could not delete bank {bank_id!r}: {exc}") from exc
        except (OpenApiException, TimeoutError, OSError) as exc:
            raise MemoryUnavailableError(f"Could not delete bank {bank_id!r}: {exc}") from exc
        finally:
            logger.info(
                "memory.delete_bank bank=%s duration_ms=%d",
                bank_id,
                int((time.monotonic() - started) * 1000),
            )


def _demo_today_iso() -> str:
    return datetime.combine(settings.demo_today, datetime.min.time()).isoformat()


def _as_dict(raw: Any) -> dict[str, Any] | None:
    """`get_memory` is typed `object` (empty schema); accept a dict or a model."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    dump = getattr(raw, "model_dump", None)
    if callable(dump):
        dumped = dump()
        return dumped if isinstance(dumped, dict) else None
    return dict(vars(raw))


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def meeting_fields(
    *, metadata: dict[str, Any] | None, tags: Sequence[str], mentioned_at: Any
) -> tuple[str | None, date | None]:
    """(meeting_id, meeting_date) for one memory from its own fields.

    World facts carry both in `metadata`. Observations have EMPTY metadata, so the
    id comes from a single `meeting:<id>` tag and the date from `mentioned_at`.
    `occurred_start` / `occurred_end` are never used (they are event dates in the text).
    """
    metadata = metadata or {}
    meeting_id = metadata.get("meeting_id") or meeting_id_from_tags(tags)
    meeting_date = _parse_date(metadata.get("meeting_date")) or _parse_date(mentioned_at)
    return meeting_id, meeting_date


def _words(text: str) -> set[str]:
    return {w for w in text.lower().split() if len(w) > 3}


def choose_meeting_from_sources(
    text: str, sources: Sequence[tuple[str, date | None, str]]
) -> tuple[str, date | None] | None:
    """Pick the meeting an observation was consolidated from.

    `sources` are `(meeting_id, meeting_date, source_text)` for the resolvable source
    memories. Choose the source whose text shares the most words with the observation;
    ties go to the latest meeting date. `None` if there are no resolvable sources.
    """
    if not sources:
        return None
    target = _words(text)
    best = max(
        sources,
        key=lambda s: (len(target & _words(s[2])), s[1] or date.min),
    )
    return best[0], best[1]


async def resolve_hit_from_payload(
    hit: MemoryHit,
    payload: dict[str, Any],
    fetch: Any,
) -> MemoryHit:
    tags = [str(t) for t in (payload.get("tags") or [])]
    meeting_id, meeting_date = meeting_fields(
        metadata=payload.get("metadata"),
        tags=tags,
        mentioned_at=payload.get("mentioned_at"),
    )
    if meeting_id is None:
        text = str(payload.get("text") or hit.text)
        resolved = await _resolve_via_sources(text, payload, fetch)
        if resolved is not None:
            meeting_id, meeting_date = resolved[0], resolved[1] or meeting_date
    return hit.model_copy(
        update={
            "meeting_id": meeting_id,
            "meeting_date": meeting_date,
            "tags": tags or hit.tags,
        }
    )


async def _resolve_via_sources(
    text: str, payload: dict[str, Any], fetch: Any
) -> tuple[str, date | None] | None:
    source_ids = [str(i) for i in (payload.get("source_memory_ids") or [])]
    embedded = {
        str(m.get("id")): m
        for m in (payload.get("source_memories") or [])
        if isinstance(m, dict) and m.get("id")
    }
    candidates: list[tuple[str, date | None, str]] = []
    for source_id in source_ids or list(embedded):
        source = embedded.get(source_id)
        if source is None or not (source.get("metadata") or source.get("tags")):
            source = await fetch(source_id)
        if source is None:
            continue
        s_tags = [str(t) for t in (source.get("tags") or [])]
        s_id, s_date = meeting_fields(
            metadata=source.get("metadata"),
            tags=s_tags,
            mentioned_at=source.get("mentioned_at"),
        )
        if s_id is not None:
            candidates.append((s_id, s_date, str(source.get("text") or "")))
    return choose_meeting_from_sources(text, candidates)


def _hit_from_recall_result(result: Any) -> MemoryHit:
    tags = list(result.tags or [])
    meeting_id, meeting_date = meeting_fields(
        metadata=result.metadata,
        tags=tags,
        mentioned_at=getattr(result, "mentioned_at", None),
    )
    return MemoryHit(
        memory_id=result.id,
        text=result.text,
        meeting_id=meeting_id,
        meeting_date=meeting_date,
        tags=tags,
    )


def _hit_from_reflect_fact(fact: Any) -> MemoryHit:
    # `ReflectFact` (from `based_on.memories`) only carries id/text/type/context/
    # occurred_start/occurred_end -- no tags or metadata. `occurred_*` is the date of an
    # event mentioned in the text, NOT the meeting date, so it is never used; meeting_id
    # and meeting_date are filled later by `MemoryService.resolve_sources`.
    return MemoryHit(
        memory_id=fact.id,
        text=fact.text,
        meeting_id=None,
        meeting_date=None,
        tags=[],
    )
