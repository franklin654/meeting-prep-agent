"""SQLite-backed contact profiles and explicit, cached contact-pattern derivation."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from typing import Any, Literal, cast

from app.core.errors import NotFoundError
from app.core.time import utcnow
from app.db import facts_repo, overrides_repo, repository
from app.db.brief_repo import SessionFactory
from app.db.models import Contact, ExtractedFact, Meeting
from app.llm.client import LLMClient
from app.llm.prompt_loader import render_prompt
from app.schemas.api import (
    AccountResponse,
    ContactMeetingTimeline,
    ContactProfile,
    ContactProfileStats,
    ContactRef,
    ProfileCommitment,
    ProfileFact,
    ProfileTimelineItem,
)
from app.schemas.brief import Citation, SourceType
from app.schemas.enums import CommitmentStatus, FactKind
from app.schemas.patterns import ContactPattern, ContactPatternDraft, PatternRefreshResponse
from app.services.evidence import QUOTE_MAX_CHARS, truncate

logger = logging.getLogger(__name__)


def _meeting_date(meeting: Meeting) -> date:
    return meeting.scheduled_at.date()


def _citation(
    meeting: Meeting, quote: str, *, source_type: SourceType = SourceType.meeting
) -> Citation:
    day = _meeting_date(meeting)
    return Citation(
        source_type=source_type,
        meeting_id=meeting.id,
        meeting_date=day,
        label=f"{meeting.title} · {day:%b} {day.day}",
        quote=truncate(quote, QUOTE_MAX_CHARS),
        memory_id=None,
    )


def build_contact_profile(contact_id: str, *, session_factory: SessionFactory) -> ContactProfile:
    with session_factory() as session:
        contact = repository.get_contact(session, contact_id)
        if contact is None:
            raise NotFoundError(f"Contact {contact_id!r} not found.")
        if contact.account_id is None:
            raise NotFoundError(f"Contact {contact_id!r} has no customer account.")
        account = repository.get_account(session, contact.account_id)
        if account is None:
            raise NotFoundError(f"Account {contact.account_id!r} not found.")
        meetings = repository.list_meetings_for_account(session, account.id)
        meeting_by_id = {meeting.id: meeting for meeting in meetings}
        attended_ids = {
            meeting.id
            for meeting in meetings
            if any(
                attendee.contact_id == contact_id
                for attendee in repository.list_attendees_for_meeting(session, meeting.id)
            )
        }
        facts = [
            fact
            for fact in facts_repo.list_account_facts(session, account.id)
            if fact.contact_id == contact_id
        ]
        all_overrides = overrides_repo.list_overrides(session)
        hidden_fact_ids = {
            override.target_id
            for override in all_overrides
            if override.target_type == "fact" and override.action in {"hidden", "corrected"}
        }
        visible_facts = [fact for fact in facts if fact.id not in hidden_fact_ids]
        hidden_count = sum(fact.id in hidden_fact_ids for fact in facts)
        commitments = [
            commitment
            for commitment in repository.list_commitments_for_account(session, account.id)
            if commitment.contact_id == contact_id
        ]
        open_followups = [
            commitment for commitment in commitments if commitment.status == CommitmentStatus.open
        ]
        timeline_items: dict[str, list[ProfileTimelineItem]] = defaultdict(list)
        profile_facts: list[ProfileFact] = []
        for fact in visible_facts:
            meeting = meeting_by_id.get(fact.meeting_id)
            if meeting is None:
                continue
            citation = _citation(meeting, fact.source_quote or fact.text)
            day = _meeting_date(meeting)
            profile_facts.append(
                ProfileFact(
                    id=fact.id,
                    kind=fact.kind,
                    text=fact.text,
                    learned_on=day,
                    citation=citation,
                )
            )
            timeline_items[meeting.id].append(
                ProfileTimelineItem(
                    kind=fact.kind.value,
                    text=fact.text,
                    learned_on=day,
                    citation=citation,
                )
            )
        followups: list[ProfileCommitment] = []
        for commitment in commitments:
            meeting = meeting_by_id.get(commitment.meeting_id)
            if meeting is None:
                continue
            citation = _citation(
                meeting, commitment.source_quote or commitment.text, source_type=SourceType.ledger
            )
            day = _meeting_date(meeting)
            followups.append(
                ProfileCommitment(
                    id=commitment.id,
                    owner=commitment.owner,
                    text=commitment.text,
                    due_date=commitment.due_date,
                    status=commitment.status,
                    citation=citation,
                )
            )
            timeline_items[meeting.id].append(
                ProfileTimelineItem(
                    kind="commitment",
                    text=commitment.text,
                    learned_on=day,
                    citation=citation,
                )
            )
        timeline = [
            ContactMeetingTimeline(
                meeting_id=meeting.id,
                title=meeting.title,
                meeting_date=_meeting_date(meeting),
                items=timeline_items[meeting.id],
            )
            for meeting in sorted(
                (meeting_by_id[meeting_id] for meeting_id in timeline_items),
                key=lambda row: (row.scheduled_at, row.id),
                reverse=True,
            )
        ]
        cached = repository.get_contact_pattern_cache(session, contact_id)
        patterns = [ContactPattern.model_validate(row) for row in cached.patterns] if cached else []
        return ContactProfile(
            contact=ContactRef(id=contact.id, name=contact.name, role=contact.role),
            account=AccountResponse(
                id=account.id,
                name=account.name,
                industry=account.industry,
                stage=cast(
                    Literal["discovery", "evaluation", "closed_won", "closed_lost"],
                    account.stage,
                ),
            ),
            stats=ContactProfileStats(
                meetings=len(attended_ids),
                facts=len(profile_facts),
                open_follow_ups=len(open_followups),
            ),
            timeline=timeline,
            facts=profile_facts,
            follow_ups=followups,
            preferences=[fact for fact in profile_facts if fact.kind == FactKind.personal],
            patterns=patterns,
            hidden_count=hidden_count,
        )


def _visible_contact_facts(
    contact_id: str, session_factory: SessionFactory
) -> tuple[Contact, Any, list[ExtractedFact]]:
    with session_factory() as session:
        contact = repository.get_contact(session, contact_id)
        if contact is None or contact.account_id is None:
            raise NotFoundError(f"Contact {contact_id!r} not found.")
        account = repository.get_account(session, contact.account_id)
        if account is None:
            raise NotFoundError(f"Account {contact.account_id!r} not found.")
        facts = [
            fact
            for fact in facts_repo.list_account_facts(session, account.id)
            if fact.contact_id == contact_id
        ]
        hidden = {
            override.target_id
            for override in overrides_repo.list_overrides(session, target_type="fact")
            if override.action in {"hidden", "corrected"}
        }
    return contact, account, [fact for fact in facts if fact.id not in hidden]


async def refresh_contact_patterns(
    contact_id: str,
    *,
    llm: LLMClient,
    session_factory: SessionFactory,
) -> PatternRefreshResponse:
    contact, account, facts = _visible_contact_facts(contact_id, session_factory)
    facts = facts[-40:]
    if len({fact.meeting_id for fact in facts}) < 2:
        with session_factory() as session:
            cached = repository.get_contact_pattern_cache(session, contact_id)
        cached_patterns = (
            [ContactPattern.model_validate(row) for row in cached.patterns] if cached else []
        )
        return PatternRefreshResponse(
            patterns=cached_patterns,
            reason="Needs facts from at least 2 meetings",
        )
    if len(facts) < 3:
        with session_factory() as session:
            cached = repository.get_contact_pattern_cache(session, contact_id)
        cached_patterns = (
            [ContactPattern.model_validate(row) for row in cached.patterns] if cached else []
        )
        return PatternRefreshResponse(
            patterns=cached_patterns, reason="Needs at least 3 visible facts"
        )
    facts_by_id = {fact.id: fact for fact in facts}
    prompt = render_prompt(
        "derive_patterns",
        contact_name=contact.name,
        contact_role=contact.role or "role not recorded",
        account_name=account.name,
        facts="\n".join(
            f"[{fact.id}] ({fact.kind.value}) {fact.text} | "
            f"source: {truncate(fact.source_quote, 180)}"
            for fact in facts
        ),
    )
    draft = await llm.complete_json(prompt, ContactPatternDraft)
    patterns: list[ContactPattern] = []
    for suggestion in draft.patterns[:4]:
        valid_ids = list(
            dict.fromkeys(fact_id for fact_id in suggestion.fact_ids if fact_id in facts_by_id)
        )
        if not valid_ids:
            continue
        citations: list[Citation] = []
        for fact_id in valid_ids:
            fact = facts_by_id[fact_id]
            with session_factory() as session:
                meeting = repository.get_meeting(session, fact.meeting_id)
            if meeting is not None:
                citations.append(_citation(meeting, fact.source_quote or fact.text))
        if citations:
            patterns.append(
                ContactPattern(text=suggestion.text, fact_ids=valid_ids, citations=citations)
            )
    with session_factory() as session:
        repository.save_contact_pattern_cache(
            session,
            contact_id,
            [pattern.model_dump(mode="json") for pattern in patterns],
            utcnow(),
        )
    logger.info(
        "contact.patterns_refreshed contact=%s facts=%d patterns=%d",
        contact_id,
        len(facts),
        len(patterns),
    )
    return PatternRefreshResponse(patterns=patterns)
