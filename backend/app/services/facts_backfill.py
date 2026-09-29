"""Sequential, resumable P1-only extraction backfill for extracted_facts."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field

from sqlmodel import Session

from app.db import facts_repo
from app.llm.client import LLMClient
from app.llm.prompt_loader import render_prompt
from app.schemas.extraction import MeetingExtraction
from app.services.ingest import OUR_COMPANY, _Resolver, _verify_quotes

SessionFactory = Callable[[], AbstractContextManager[Session]]


@dataclass
class BackfillResult:
    eligible: int = 0
    processed: list[str] = field(default_factory=list)
    facts_by_kind: Counter[str] = field(default_factory=Counter)
    facts_by_meeting: dict[str, Counter[str]] = field(default_factory=dict)
    meetings_with_two_facts: int = 0
    calls: int = 0


async def backfill_facts(
    session_factory: SessionFactory,
    llm: LLMClient | None,
    *,
    dry_run: bool = False,
    limit: int | None = None,
) -> BackfillResult:
    """Process eligible meetings in order. This function never calls Hindsight."""
    result = BackfillResult()
    with session_factory() as session:
        candidates = facts_repo.list_backfill_candidates(session, limit=limit)
        result.eligible = len(candidates)
        if dry_run:
            return result
        if llm is None:
            raise ValueError("An LLM client is required unless --dry-run is set.")

        for meeting, account in candidates:
            transcript = meeting.transcript
            if not transcript:
                continue
            resolver = _Resolver.load(session, account.id)
            prompt = render_prompt(
                "extract_meeting",
                our_company=OUR_COMPANY,
                our_people=", ".join(contact.name for contact in resolver.own_contacts) or "(none)",
                meeting_title=meeting.title,
                meeting_date=meeting.scheduled_at.date().isoformat(),
                account_name=account.name,
                known_contacts="; ".join(
                    f"{contact.name} ({contact.role})" if contact.role else contact.name
                    for contact in resolver.account_contacts
                )
                or "(none)",
                transcript=transcript,
            )
            extraction = await llm.complete_json(prompt, MeetingExtraction, temperature=0.0)
            result.calls += 1
            verified = _verify_quotes(extraction, transcript)
            rows = []
            meeting_counts: Counter[str] = Counter()
            for fact in verified.facts:
                text = fact.text.strip()
                if not text:
                    continue
                contact = resolver.find(fact.about_person) if fact.about_person else None
                rows.append(
                    (
                        contact.id if contact else None,
                        fact.kind,
                        text,
                        fact.source_quote.strip()[:200],
                    )
                )
                result.facts_by_kind[fact.kind.value] += 1
                meeting_counts[fact.kind.value] += 1
            facts_repo.replace_meeting_facts(session, meeting.id, account.id, rows)
            result.processed.append(meeting.id)
            result.facts_by_meeting[meeting.id] = meeting_counts
            if len(rows) >= 2:
                result.meetings_with_two_facts += 1
    return result
