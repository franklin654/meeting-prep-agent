"""A1 additive-table repository tests; each runs against the temporary SQLite DB."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Session

from app.db import capture_repo, facts_repo, overrides_repo
from app.db.models import Account, Meeting
from app.schemas.enums import FactKind


def _meeting(session: Session) -> None:
    session.add(Account(id="acc_x", name="X", industry="tech", stage="discovery"))
    session.add(
        Meeting(
            id="m_x", account_id="acc_x", title="Call",
            scheduled_at=datetime(2026, 9, 1, tzinfo=UTC), status="done",
        )
    )
    session.commit()


def test_facts_replace_and_list_for_account(session: Session) -> None:
    _meeting(session)
    created = facts_repo.replace_meeting_facts(
        session, "m_x", "acc_x", [(None, FactKind.objection, "Security review", "Need SOC 2")]
    )
    facts_repo.replace_meeting_facts(
        session, "m_x", "acc_x", [(None, FactKind.deal_fact, "Budget is $40K", "Budget is $40K")]
    )

    assert len(created) == 1
    facts = facts_repo.list_account_facts(session, "acc_x")
    assert [(fact.kind, fact.text) for fact in facts] == [(FactKind.deal_fact, "Budget is $40K")]


def test_capture_draft_and_prepared_state(session: Session) -> None:
    _meeting(session)
    draft = capture_repo.create_draft(
        session, meeting_id="m_x", transcript="Transcript", extraction={"facts": []}, items=[]
    )
    assert capture_repo.get_draft(session, draft.id) is not None
    assert capture_repo.set_draft_status(session, draft.id, "discarded").status == "discarded"

    capture_repo.mark_prepared(session, "m_x")
    assert capture_repo.is_prepared(session, "m_x") is True
    capture_repo.unmark_prepared(session, "m_x")
    assert capture_repo.is_prepared(session, "m_x") is False


def test_memory_override_create_and_list(session: Session) -> None:
    override = overrides_repo.create_override(
        session, target_type="fact", target_id="fact_1", action="hidden", corrected_text=None
    )
    assert override.target_id == "fact_1"
    assert overrides_repo.list_overrides(session, target_type="fact")[0].action == "hidden"
