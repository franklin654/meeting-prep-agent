"""Round-trip tests for docs/data-model-and-schemas.md
"API models, jobs and errors" (T05)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.schemas.api import (
    ContactRef,
    ContactTimeline,
    ErrorBody,
    ErrorResponse,
    FeedbackRequest,
    JobAccepted,
    JobStatus,
    LearnedSummary,
    MeetingSummary,
    NotesRequest,
    Nudge,
    StyleProfile,
    TimelineEntry,
)
from app.schemas.brief import Citation, SectionKey, SourceType
from app.schemas.enums import FactKind
from tests.unit.schema_helpers import round_trip


def _contact_ref() -> ContactRef:
    return ContactRef(id="c_rahul", name="Rahul", role="VP Eng")


def test_contact_ref_round_trips_with_null_role() -> None:
    round_trip(_contact_ref())
    round_trip(ContactRef(id="c_unknown", name="Unknown", role=None))


def test_meeting_summary_round_trips() -> None:
    summary = MeetingSummary(
        id="m5_finedge",
        account_id="acc_finedge",
        account_name="FinEdge",
        title="Pilot follow-up",
        scheduled_at=datetime(2026, 9, 2, 10, 0, tzinfo=UTC),
        status="upcoming",
        attendees=[_contact_ref()],
        brief_ready=False,
    )
    round_trip(summary)


def test_notes_request_enforces_min_length() -> None:
    round_trip(NotesRequest(transcript="x" * 50))
    with pytest.raises(ValidationError):
        NotesRequest(transcript="too short")


def test_job_accepted_round_trips() -> None:
    round_trip(JobAccepted(job_id="job_1a2b3c4d"))


def test_learned_summary_round_trips() -> None:
    round_trip(
        LearnedSummary(
            facts=["Budget now $75K (was $40K)"],
            new_commitments=1,
            closed_commitments=2,
            alerts=["Budget contradiction"],
        )
    )


def test_job_status_round_trips_pending_and_done() -> None:
    round_trip(JobStatus(id="job_1", kind="ingest", status="pending"))
    round_trip(
        JobStatus(
            id="job_1",
            kind="ingest",
            status="done",
            learned=LearnedSummary(
                facts=[], new_commitments=0, closed_commitments=0, alerts=[]
            ),
            error=None,
        )
    )
    with pytest.raises(ValidationError):
        JobStatus(id="job_1", kind="ingest", status="running")  # type: ignore[arg-type]


def test_timeline_entry_and_contact_timeline_round_trip() -> None:
    entry = TimelineEntry(
        text="Budget moved to about $75K",
        fact_kind=FactKind.deal_fact,
        learned_on=date(2026, 9, 2),
        citation=Citation(
            source_type=SourceType.meeting,
            meeting_id="m5_finedge",
            meeting_date=date(2026, 9, 2),
            label="Call on Sep 2, 2026",
            quote=None,
            memory_id="mem_1",
        ),
    )
    round_trip(entry)

    timeline = ContactTimeline(contact=_contact_ref(), entries=[entry])
    round_trip(timeline)


def test_feedback_request_round_trips_and_rejects_bad_action() -> None:
    round_trip(FeedbackRequest(section=SectionKey.personal_touchpoints, action="collapsed"))
    with pytest.raises(ValidationError):
        FeedbackRequest(
            section=SectionKey.personal_touchpoints, action="dismiss"  # type: ignore[arg-type]
        )


def test_style_profile_round_trips() -> None:
    round_trip(
        StyleProfile(
            section_order=[SectionKey.attendees, SectionKey.open_commitments],
            hidden_sections=[SectionKey.personal_touchpoints],
            length="standard",
            notes=["Prefers shorter briefs"],
        )
    )


def test_nudge_round_trips() -> None:
    round_trip(
        Nudge(
            kind="overdue_commitment",
            text="Pricing deck to Rahul is overdue",
            link="/meetings/m5_finedge",
        )
    )


def test_error_body_and_response_round_trip() -> None:
    round_trip(ErrorBody(code="not_found", message="Unknown meeting"))
    round_trip(ErrorResponse(error=ErrorBody(code="not_found", message="Unknown meeting")))
