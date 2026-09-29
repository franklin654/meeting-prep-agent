"""Post-ingest reasoning for account-scoped contradictions (R2)."""

from __future__ import annotations

import logging
from datetime import date

from pydantic import ValidationError as PydanticValidationError

from app.core.time import today
from app.llm.prompt_loader import render_prompt
from app.memory.memory_service import MemoryService
from app.memory.tags import account_tag
from app.schemas.memory import MemoryHit
from app.schemas.reasoning import ContradictionReport
from app.services.evidence import format_date

logger = logging.getLogger(__name__)


async def check_changes(
    *,
    memory: MemoryService,
    account_id: str,
    account_name: str,
    meeting_id: str,
    meeting_date: date,
) -> list[str]:
    """Return only contradictions whose earlier and new source meetings resolve."""
    query = render_prompt(
        "reflect_contradictions",
        today=today().isoformat(),
        account_name=account_name,
        meeting_date=meeting_date.isoformat(),
    )
    result = await memory.reflect_structured(
        query=query,
        tags=[account_tag(account_id)],
        schema=ContradictionReport,
        budget="high",
    )
    if result.structured is None:
        logger.warning(
            "reasoning.r2.dropped reason=%s",
            result.structured_error or "no structured output",
        )
        return []
    try:
        report = ContradictionReport.model_validate(result.structured)
    except PydanticValidationError:
        logger.warning("reasoning.r2.dropped reason=invalid_output")
        return []
    if not report.contradictions:
        return []

    sources = await memory.resolve_sources(result.sources)
    alerts: list[str] = []
    for contradiction in report.contradictions:
        if contradiction.new_date != meeting_date:
            logger.info(
                "reasoning.r2.dropped topic=%s reason=wrong_new_date", contradiction.topic
            )
            continue
        earlier = _source_for_date(sources, contradiction.earlier_date)
        current = next(
            (
                source
                for source in sources
                if source.meeting_id == meeting_id and source.meeting_date == meeting_date
            ),
            None,
        )
        if earlier is None or current is None or earlier.meeting_id == current.meeting_id:
            logger.info(
                "reasoning.r2.dropped topic=%s reason=missing_source_pair", contradiction.topic
            )
            continue
        alerts.append(
            f"{contradiction.summary} Earlier: {contradiction.earlier_value} "
            f"({earlier.meeting_id}, {format_date(contradiction.earlier_date)}); "
            f"new: {contradiction.new_value} "
            f"({current.meeting_id}, {format_date(meeting_date)})."
        )
    return alerts


def _source_for_date(sources: list[MemoryHit], source_date: date) -> MemoryHit | None:
    return next(
        (source for source in sources if source.meeting_id and source.meeting_date == source_date),
        None,
    )
