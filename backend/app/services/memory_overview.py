"""Read models for the Memory inspector; SQLite is authoritative for app facts."""

from __future__ import annotations

import logging
from typing import Literal, cast

from app.db import repository
from app.db.brief_repo import SessionFactory
from app.db.models import Meeting, MemoryOverride
from app.memory.memory_service import MemoryService
from app.schemas.api import (
    AccountMemoryGrowth,
    HiddenMemoryItem,
    HindsightBankStats,
    MemoryGrowthPoint,
    MemoryOverview,
)
from app.schemas.enums import FactKind
from app.services.preferences import current_style

logger = logging.getLogger(__name__)


async def get_memory_overview(
    session_factory: SessionFactory, memory: MemoryService
) -> MemoryOverview:
    with session_factory() as session:
        accounts = {row.id: row for row in repository.list_accounts(session)}
        meetings = repository.list_all_meetings(session)
        facts = repository.list_all_extracted_facts(session)
        overrides = repository.list_all_memory_overrides(session)

    active_override: dict[tuple[str, str], MemoryOverride] = {}
    for override in overrides:
        key = (override.target_type, override.target_id)
        if override.action in {"hidden", "corrected"}:
            active_override[key] = override
        else:
            active_override.pop(key, None)
    hidden_fact_ids = {
        target_id for target_type, target_id in active_override if target_type == "fact"
    }
    visible_facts = [fact for fact in facts if fact.id not in hidden_fact_ids]
    facts_by_kind = {kind: 0 for kind in FactKind}
    for fact in visible_facts:
        facts_by_kind[fact.kind] += 1

    facts_by_meeting: dict[str, int] = {}
    for fact in visible_facts:
        facts_by_meeting[fact.meeting_id] = facts_by_meeting.get(fact.meeting_id, 0) + 1
    meetings_by_account: dict[str, list[Meeting]] = {}
    for meeting in meetings:
        if meeting.status == "done":
            meetings_by_account.setdefault(meeting.account_id, []).append(meeting)
    growth: list[AccountMemoryGrowth] = []
    for account_id, account in accounts.items():
        count = 0
        points = []
        for meeting in meetings_by_account.get(account_id, []):
            count += facts_by_meeting.get(meeting.id, 0)
            points.append(
                MemoryGrowthPoint(
                    meeting_id=meeting.id,
                    meeting_title=meeting.title,
                    meeting_date=meeting.scheduled_at.date(),
                    fact_count=count,
                )
            )
        if points:
            growth.append(
                AccountMemoryGrowth(account_id=account_id, account_name=account.name, points=points)
            )

    fact_by_id = {fact.id: fact for fact in facts}
    meeting_by_id = {meeting.id: meeting for meeting in meetings}
    hidden_items: list[HiddenMemoryItem] = []
    for (target_type, target_id) in sorted(active_override):
        found_fact = fact_by_id.get(target_id) if target_type == "fact" else None
        source_meeting = meeting_by_id.get(found_fact.meeting_id) if found_fact else None
        hidden_items.append(
            HiddenMemoryItem(
                target_id=target_id,
                target_type=cast(Literal["fact", "memory"], target_type),
                text=(
                    found_fact.text
                    if found_fact
                    else "Hidden memory item (still retained in Hindsight)"
                ),
                meeting_id=source_meeting.id if source_meeting else None,
                meeting_title=source_meeting.title if source_meeting else None,
                meeting_date=source_meeting.scheduled_at.date() if source_meeting else None,
            )
        )

    try:
        raw_stats = await memory.get_bank_stats(timeout_s=2.0)
        stats = HindsightBankStats.model_validate(raw_stats) if raw_stats is not None else None
    except Exception as exc:
        logger.info(
            "memory_overview.hindsight_stats status=unavailable error=%s", type(exc).__name__
        )
        stats = None

    return MemoryOverview(
        facts_by_kind=facts_by_kind,
        growth=growth,
        hidden_item_count=len(hidden_items),
        hidden_items=hidden_items,
        style_rules=current_style(session_factory),
        hindsight_stats=stats,
    )
