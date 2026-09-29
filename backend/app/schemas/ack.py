"""P2 output: docs/prompt-specs.md "P2 match_acknowledgements.md".

`AckMatches` is LLM-facing, so it forbids extra fields (docs/data-model-and-schemas.md
"Conventions"). It changes only together with `prompts/match_acknowledgements.md`.
The prompt spec names the item class `AckMatch`; the ticket names it `ClosedMatch`, so
`AckMatch` is kept as an alias.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ClosedMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commitment_id: str
    acknowledgement_index: int


AckMatch = ClosedMatch


class AckMatches(BaseModel):
    model_config = ConfigDict(extra="forbid")

    closed: list[ClosedMatch]
