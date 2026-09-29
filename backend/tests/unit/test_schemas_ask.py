"""Round-trip tests for docs/data-model-and-schemas.md "Ask panel" (T05)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.ask import (
    UNGROUNDED_REPLY,
    AskRequest,
    AskResponse,
    AskTurn,
    NoteRequest,
    PinRequest,
    ReflectAnswer,
)
from app.schemas.brief import Citation, SourceType
from app.schemas.enums import ScopeType
from tests.unit.schema_helpers import round_trip


def test_ungrounded_reply_constant() -> None:
    assert UNGROUNDED_REPLY == "Nothing in memory covers that yet."


def test_ask_turn_round_trips() -> None:
    round_trip(AskTurn(question="What is the budget?", answer="$75K as of Sep 2026"))


def test_ask_request_round_trips_with_default_history() -> None:
    request = AskRequest(
        question="What did Anita say about Q4 budget?",
        scope_type=ScopeType.account,
        scope_id="acc_finedge",
    )
    assert request.history == []
    round_trip(request)


def test_ask_request_enforces_field_constraints() -> None:
    with pytest.raises(ValidationError):
        AskRequest(question="ab", scope_type=ScopeType.account, scope_id="acc_finedge")
    with pytest.raises(ValidationError):
        AskRequest(question="x" * 501, scope_type=ScopeType.account, scope_id="acc_finedge")
    with pytest.raises(ValidationError):
        AskRequest(
            question="valid question",
            scope_type=ScopeType.account,
            scope_id="acc_finedge",
            history=[AskTurn(question="q", answer="a") for _ in range(4)],
        )


def test_reflect_answer_round_trips_and_ignores_extra() -> None:
    round_trip(ReflectAnswer(answer="Budget is $75K", confident=True))
    assert ReflectAnswer.model_validate(
        {"answer": "Budget is $75K", "confident": True, "extra_field": "x"}
    ) == ReflectAnswer(answer="Budget is $75K", confident=True)


def test_ask_response_round_trips() -> None:
    response = AskResponse(
        ask_answer_id="ask_1a2b3c4d",
        answer="Budget is $75K as of the Sep 2026 call",
        grounded=True,
        citations=[
            Citation(
                source_type=SourceType.meeting,
                meeting_id="m5_finedge",
                meeting_date=None,
                label="Call on Sep 2, 2026",
                quote=None,
                memory_id="mem_1",
            )
        ],
    )
    round_trip(response)


def test_pin_and_note_request_round_trip_and_constraints() -> None:
    round_trip(PinRequest(meeting_id="m5_finedge"))
    round_trip(
        NoteRequest(text="Remember this", scope_type=ScopeType.contact, scope_id="c_rahul")
    )
    with pytest.raises(ValidationError):
        NoteRequest(text="ab", scope_type=ScopeType.contact, scope_id="c_rahul")
