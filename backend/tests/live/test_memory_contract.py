"""Live Hindsight contract test (docs/hindsight-integration.md "Testing":
"a small live test (marked `@pytest.mark.live`) retains one document, waits
until idle, recalls it by tag, and reflects with a tiny schema. Run it first
whenever the SDK version changes.").

Requires a real, running Hindsight container reachable at `settings.hindsight_url`
(`docker compose up -d hindsight`) with a Groq model configured that supports
tool calling (reflect fails otherwise -- see docs/hindsight-integration.md
"Setup"). Run with:

    uv run pytest -m live -v
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from pydantic import BaseModel

from app.memory.memory_service import HindsightMemoryService
from app.memory.tags import account_tag

pytestmark = pytest.mark.live


class _TinyAnswer(BaseModel):
    answer: str
    confident: bool


async def test_retain_wait_recall_and_reflect_round_trip() -> None:
    service = HindsightMemoryService()
    run_id = uuid.uuid4().hex[:8]
    account_id = f"acc-contract-test-{run_id}"
    meeting_id = f"contract-test-{run_id}"

    try:
        # 1. bootstrap: bank + fact_kind entity label.
        await service.ensure_bank()

        # 2. retain one document -- a meeting transcript, stable id.
        await service.retain_meeting(
            meeting_id=meeting_id,
            account_id=account_id,
            contact_ids=[f"c-contract-test-{run_id}"],
            meeting_date=date(2026, 8, 27),
            title="Contract test meeting",
            transcript=(
                "Priya (2026-08-27T10:00:00Z): Before we can move to a pilot, what's "
                "still outstanding on your end?\n"
                "Rahul (2026-08-27T10:01:00Z): We still need your SOC 2 report -- "
                "procurement won't sign off without it. Budget-wise we're planning "
                "around $50,000 for the first year."
            ),
        )

        # 3. wait until idle before reading back (read-after-write).
        # 240s: observed live that a single consolidation pass can hit Groq's
        # free-tier TPM limit and back off ~3 minutes before its own retry
        # (docs/hindsight-integration.md "Failure handling": "Groq 429 inside
        # Hindsight surfaces as slow or failed operations").
        idle = await service.wait_until_idle(timeout_s=240)
        assert idle, "Hindsight did not go idle within 240s after retain"

        # 4. recall it by tag.
        hits = await service.recall_facts(
            query="SOC 2 compliance report", tags=[account_tag(account_id)]
        )
        assert hits, "recall_facts found nothing for the just-retained meeting"
        assert any(hit.meeting_id == meeting_id for hit in hits), (
            f"no recalled hit carries meeting_id={meeting_id!r}: {hits}"
        )

        # 5. reflect with a tiny response_schema.
        result = await service.reflect_structured(
            query="What compliance requirement did Rahul mention as a blocker?",
            tags=[account_tag(account_id)],
            schema=_TinyAnswer,
            budget="mid",
        )
        assert result.structured_error is None, (
            f"reflect's structured_output_error persisted: {result.structured_error}"
        )
        assert result.structured is not None
        parsed = _TinyAnswer.model_validate(result.structured)
        assert "soc 2" in parsed.answer.lower() or "soc2" in parsed.answer.lower()
    finally:
        await service.aclose()
