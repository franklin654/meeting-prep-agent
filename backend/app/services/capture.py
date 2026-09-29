"""Preview and save reviewed meeting captures without extracting twice."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from typing import Literal

from sqlmodel import Session

from app.core.errors import AppError, NotFoundError
from app.db import capture_repo, entities_repo, facts_repo, ingest_repo, meetings_repo, repository
from app.db.models import Commitment, Meeting
from app.llm.client import LLMClient
from app.llm.prompt_loader import render_prompt
from app.memory.memory_service import MemoryService
from app.schemas.ack import AckMatches
from app.schemas.api import CaptureDraftResponse, CaptureItem, LearnedSummary
from app.schemas.enums import CommitmentStatus, FactKind, Owner
from app.schemas.extraction import MeetingExtraction
from app.services.ingest import (
    INGEST_RETAIN_TIMEOUT_S,
    OUR_COMPANY,
    SessionFactory,
    _format_ack,
    _format_new_commitment,
    _format_open_commitment,
    _match_commitment_ids,
    _match_renewed_commitments,
    _Resolver,
    _verify_quotes,
    is_verbatim,
    normalize_text,
    safe_error_message,
)

logger = logging.getLogger(__name__)


def _similar(a: str, b: str) -> bool:
    left = set(re.sub(r"[^\w\s]", " ", normalize_text(a)).split())
    right = set(re.sub(r"[^\w\s]", " ", normalize_text(b)).split())
    return bool(left and right and len(left & right) / len(left | right) >= 0.8)


def _make_items(
    session: Session,
    meeting: Meeting,
    extraction: MeetingExtraction,
    transcript: str,
    matches: AckMatches,
    closed_ids: set[str],
    renewed_by_index: dict[int, str],
) -> list[CaptureItem]:
    commitments = repository.list_commitments_for_account(session, meeting.account_id)
    open_rows = [c for c in commitments if c.status == CommitmentStatus.open]
    facts = facts_repo.list_account_facts(session, meeting.account_id)
    items: list[CaptureItem] = []
    for index, commitment_item in enumerate(extraction.commitments):
        quote = commitment_item.source_quote.strip()
        if not is_verbatim(quote, normalize_text(transcript)):
            continue
        renewed_id = renewed_by_index.get(index)
        target = next((c for c in open_rows if c.id == renewed_id), None)
        dup_fact = next((f for f in facts if _similar(f.text, commitment_item.text)), None)
        dup_commit = next((c for c in open_rows if _similar(c.text, commitment_item.text)), None)
        badge: Literal["new", "closes", "duplicate", "updates_due_date"] = (
            "updates_due_date" if target else ("duplicate" if dup_fact or dup_commit else "new")
        )
        items.append(
            CaptureItem(
                id=f"commitment_{index}",
                kind="commitment",
                text=commitment_item.text.strip(),
                owner=commitment_item.owner.value,
                contact=commitment_item.owner_person or None,
                due_date=commitment_item.due_date,
                quote=quote[:200],
                badge=badge,
                target_commitment_id=target.id
                if target
                else (dup_commit.id if dup_commit else None),
                checked=badge != "duplicate",
            )
        )
    for index, ack_item in enumerate(extraction.acknowledgements):
        quote = ack_item.source_quote.strip()
        if not is_verbatim(quote, normalize_text(transcript)):
            continue
        closed = next(
            (
                match
                for match in matches.closed
                if match.acknowledgement_index == index and match.commitment_id in closed_ids
            ),
            None,
        )
        items.append(
            CaptureItem(
                id=f"closes_{index}",
                kind="closes",
                text=ack_item.description.strip(),
                quote=quote[:200],
                badge="closes" if closed else "new",
                target_commitment_id=closed.commitment_id if closed else None,
                checked=closed is not None,
            )
        )
    for index, fact_item in enumerate(extraction.facts):
        quote = fact_item.source_quote.strip()
        if not quote or normalize_text(quote) not in normalize_text(transcript):
            continue
        duplicate = any(_similar(f.text, fact_item.text) for f in facts)
        items.append(
            CaptureItem(
                id=f"fact_{index}",
                kind="fact",
                fact_kind=fact_item.kind,
                text=fact_item.text.strip(),
                contact=fact_item.about_person,
                quote=quote[:200],
                badge="duplicate" if duplicate else "new",
                checked=not duplicate,
            )
        )
    return items


def _counts(items: Sequence[CaptureItem]) -> dict[str, int]:
    return {
        "commitments": sum(item.kind == "commitment" for item in items),
        "closes": sum(item.kind == "closes" for item in items),
        "facts": sum(item.kind == "fact" for item in items),
    }


async def run_capture_preview(
    job_id: str,
    meeting_id: str,
    transcript: str,
    *,
    llm: LLMClient,
    session_factory: SessionFactory,
) -> None:
    try:
        with session_factory() as session:
            meeting = repository.get_meeting(session, meeting_id)
            if meeting is None:
                raise NotFoundError(f"Meeting {meeting_id!r} not found.")
            account = repository.get_account(session, meeting.account_id)
            if account is None:
                raise NotFoundError(f"Account {meeting.account_id!r} not found.")
            resolver = _Resolver.load(session, account.id)
            extraction = await llm.complete_json(
                render_prompt(
                    "extract_meeting",
                    our_company=OUR_COMPANY,
                    our_people=", ".join(c.name for c in resolver.own_contacts) or "(none)",
                    meeting_title=meeting.title,
                    meeting_date=meeting.scheduled_at.date().isoformat(),
                    account_name=account.name,
                    known_contacts="; ".join(c.name for c in resolver.account_contacts) or "(none)",
                    transcript=transcript,
                ),
                MeetingExtraction,
                temperature=0.0,
            )
            verified = _verify_quotes(extraction, transcript)
            extraction.commitments = verified.commitments
            extraction.acknowledgements = verified.acknowledgements
            extraction.facts = verified.facts
            open_rows = ingest_repo.list_open_commitments(session, account.id)
            matches = AckMatches(closed=[], renewed=[])
            if open_rows and (verified.acknowledgements or verified.commitments):
                matches = await llm.complete_json(
                    render_prompt(
                        "match_acknowledgements",
                        open_commitments="\n".join(_format_open_commitment(c) for c in open_rows),
                        new_commitments="\n".join(
                            _format_new_commitment(i, c) for i, c in enumerate(verified.commitments)
                        )
                        or "(none)",
                        meeting_date=meeting.scheduled_at.date().isoformat(),
                        acknowledgements="\n".join(
                            _format_ack(i, a) for i, a in enumerate(verified.acknowledgements)
                        ),
                    ),
                    AckMatches,
                    temperature=0.0,
                )
            closed_ids = set(
                _match_commitment_ids(matches, open_rows, len(verified.acknowledgements))
            )
            renewed = _match_renewed_commitments(matches, open_rows, verified.commitments, resolver)
            items = _make_items(
                session,
                meeting,
                extraction,
                transcript,
                matches,
                closed_ids,
                {index: commitment_id for commitment_id, index in renewed.items()},
            )
            draft = capture_repo.create_draft(
                session,
                meeting_id=meeting_id,
                transcript=transcript,
                extraction={
                    "p1": extraction.model_dump(mode="json"),
                    "p2": matches.model_dump(mode="json"),
                },
                items=[i.model_dump(mode="json") for i in items],
            )
            response = CaptureDraftResponse(
                draft_id=draft.id, meeting_id=meeting_id, items=items, counts=_counts(items)
            )
            ingest_repo.finish_job(
                session, job_id, result={"draft": response.model_dump(mode="json")}
            )
    except Exception as exc:
        _finish_failure(session_factory, job_id, exc)


def _finish_failure(session_factory: SessionFactory, job_id: str, exc: Exception) -> None:
    code = exc.code if isinstance(exc, AppError) else "internal_error"
    with session_factory() as session:
        ingest_repo.finish_job(
            session,
            job_id,
            error=code,
            result={"error_code": code, "error_message": safe_error_message(exc)},
        )


async def run_capture_save(
    job_id: str,
    draft_id: str,
    unchecked_item_ids: set[str],
    *,
    memory: MemoryService,
    session_factory: SessionFactory,
) -> None:
    try:
        with session_factory() as session:
            draft = capture_repo.get_draft(session, draft_id)
            if draft is None:
                raise NotFoundError(f"Capture draft {draft_id!r} not found.")
            meeting = repository.get_meeting(session, draft.meeting_id)
            if meeting is None:
                raise NotFoundError(f"Meeting {draft.meeting_id!r} not found.")
            account = repository.get_account(session, meeting.account_id)
            if account is None:
                raise NotFoundError(f"Account {meeting.account_id!r} not found.")
            extraction = MeetingExtraction.model_validate(draft.extraction["p1"])
            selected = [
                CaptureItem.model_validate(row)
                for row in draft.items
                if row.get("checked", True) and row["id"] not in unchecked_item_ids
            ]
            resolver = _Resolver.load(session, account.id)
            created = 0
            closed = 0
            learned: list[str] = []
            fact_rows: list[tuple[str | None, FactKind, str, str]] = []
            for item in selected:
                if item.kind == "closes" and item.target_commitment_id:
                    ingest_repo.mark_commitment_done(session, item.target_commitment_id, meeting.id)
                    closed += 1
                elif item.kind == "commitment":
                    owner = next(
                        (c for c in extraction.commitments if c.text.strip() == item.text), None
                    )
                    if (
                        item.badge == "updates_due_date"
                        and item.target_commitment_id
                        and item.due_date
                    ):
                        ingest_repo.update_open_commitment_due_date(
                            session, item.target_commitment_id, item.due_date
                        )
                        learned.append(item.text)
                        continue
                    if item.badge == "duplicate":
                        continue
                    contact = resolver.find(item.contact or "") if item.contact else None
                    row = Commitment(
                        id=ingest_repo.new_id("cm"),
                        account_id=account.id,
                        meeting_id=meeting.id,
                        owner=owner.owner if owner else Owner.them,
                        contact_id=contact.id if contact else None,
                        text=item.text,
                        due_date=item.due_date,
                        status=CommitmentStatus.open,
                        source_quote=item.quote,
                    )
                    repository.create_commitment(session, row)
                    created += 1
                    learned.append(item.text)
                elif item.kind == "fact" and item.fact_kind is not None:
                    contact = resolver.find(item.contact or "") if item.contact else None
                    fact_rows.append(
                        (contact.id if contact else None, item.fact_kind, item.text, item.quote)
                    )
                    learned.append(item.text)
            facts_repo.replace_meeting_facts(session, meeting.id, account.id, fact_rows)
            if extraction.deal_budget_usd is not None and any(
                i.kind == "fact" and i.fact_kind == FactKind.deal_fact for i in selected
            ):
                ingest_repo.update_account_deal_value(
                    session, account.id, extraction.deal_budget_usd
                )
            meetings_repo.save_transcript(session, meeting.id, draft.transcript)
            attendees = entities_repo.attendees_for_meeting(session, meeting.id)
            await memory.retain_meeting(
                meeting_id=meeting.id,
                account_id=account.id,
                contact_ids=[c.id for c in attendees],
                meeting_date=meeting.scheduled_at.date(),
                title=meeting.title,
                transcript=draft.transcript,
                timeout_s=INGEST_RETAIN_TIMEOUT_S,
            )
            if not await memory.wait_until_idle(timeout_s=60.0):
                raise RuntimeError("Hindsight did not become idle after capture save.")
            summary = LearnedSummary(
                facts=learned, new_commitments=created, closed_commitments=closed, alerts=[]
            )
            ingest_repo.set_meeting_ingested(session, meeting.id, ingest_repo.stamp())
            extraction_dump = dict(draft.extraction)
            extraction_dump["save_job_id"] = job_id
            capture_repo.update_draft(session, draft_id, status="saved", extraction=extraction_dump)
            ingest_repo.finish_job(session, job_id, result=summary.model_dump(mode="json"))
    except Exception as exc:
        _finish_failure(session_factory, job_id, exc)


def discard_capture(session: Session, draft_id: str) -> None:
    draft = capture_repo.get_draft(session, draft_id)
    if draft is None:
        raise NotFoundError(f"Capture draft {draft_id!r} not found.")
    if draft.status != "saved":
        capture_repo.set_draft_status(session, draft_id, "discarded")
