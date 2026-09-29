"""Ask panel: docs/data-model-and-schemas.md "Ask panel".

The Ask flow (prompt R5) uses Hindsight reflect with a `response_schema` of
`ReflectAnswer`; the API wraps the result with citations mapped the same
way as the brief.

`ReflectAnswer` is the `response_schema` handed to Hindsight reflect, i.e.
an LLM-facing output like `MeetingExtraction`/`BriefDraft`. The doc's code
block doesn't show `extra="forbid"` on it, but the "Conventions" section
says every LLM output model gets it ("so unexpected fields fail
validation") -- applied here per that stated rule. Flagged in the ticket
report as a judgment call in case the doc's code block should instead be
treated as authoritative over its own prose.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.brief import Citation
from app.schemas.enums import ScopeType

UNGROUNDED_REPLY = "Nothing in memory covers that yet."


class AskTurn(BaseModel):
    question: str
    answer: str


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    scope_type: ScopeType
    scope_id: str
    history: list[AskTurn] = Field(default_factory=list, max_length=3)


# response_schema passed to Hindsight reflect
class ReflectAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    confident: bool  # false when memory doesn't cover the question


class AskResponse(BaseModel):
    ask_answer_id: str
    answer: str  # replaced by the fixed "nothing in memory" text when ungrounded
    grounded: bool  # true only if citations is non-empty and confident
    citations: list[Citation]


class PinRequest(BaseModel):
    meeting_id: str


class NoteRequest(BaseModel):
    text: str = Field(min_length=3, max_length=1000)
    scope_type: ScopeType
    scope_id: str


class SuggestedQuestions(BaseModel):
    questions: list[str] = Field(min_length=1, max_length=3)
