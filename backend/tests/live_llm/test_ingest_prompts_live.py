"""Live twin of the P1/P2 fixture tests (docs/prompt-specs.md "Prompt rules and testing").

Run with `uv run pytest -m live_llm`. Uses the real configured app LLM (skipped when the
selected provider has no key/model, like `test_provider_smoke.py`). Keys are never printed.

- P1 on M4: the pricing-deck commitment (due 2026-09-03) and the DAG-configs commitment
  (due 2026-09-05) appear, each with a verbatim `source_quote`.
- P2 on M5: the DAG-configs commitment is closed; the pricing deck is not (the "still
  waiting on something from your side" distractor must not match).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.config import Settings
from app.llm.client import LLMClient, get_llm_client
from app.llm.prompt_loader import render_prompt
from app.schemas.ack import AckMatches
from app.schemas.extraction import ExtractedCommitment, MeetingExtraction
from app.services.ingest import INGEST_LLM_TIMEOUT_SECONDS, is_verbatim, normalize_text

pytestmark = pytest.mark.live_llm

TRANSCRIPTS = Path(__file__).resolve().parents[3] / "data" / "seed" / "transcripts"
OUR_PEOPLE = "Priya Nair, Arjun Menon"
KNOWN = (
    "Rahul Mehta (VP Engineering); Anita Desai (CFO); Karan Shah (aliases: KS; "
    "Data Platform Lead); Sneha Iyer (IT Security Manager)"
)


def _client() -> LLMClient:
    settings = Settings()
    if not settings.app_llm_api_key or not settings.llm_model:
        pytest.skip("app LLM key/model not configured for the selected provider")
    return get_llm_client(timeout_seconds=INGEST_LLM_TIMEOUT_SECONDS)


async def _extract(client: LLMClient, filename: str, title: str, day: str) -> MeetingExtraction:
    prompt = render_prompt(
        "extract_meeting",
        our_company="Tracewise",
        our_people=OUR_PEOPLE,
        meeting_title=title,
        meeting_date=day,
        account_name="FinEdge Payments",
        known_contacts=KNOWN,
        transcript=(TRANSCRIPTS / filename).read_text(encoding="utf-8"),
    )
    return await client.complete_json(prompt, MeetingExtraction, temperature=0.0)


def _find(extraction: MeetingExtraction, needle: str) -> list[ExtractedCommitment]:
    return [c for c in extraction.commitments if needle in c.text.lower()]


async def test_p1_m4_finds_deck_and_dag_configs_with_verbatim_quotes() -> None:
    client = _client()
    extraction = await _extract(
        client, "m4_finedge_pilot_scoping.txt", "Pilot scoping", "2026-08-27"
    )
    transcript = normalize_text((TRANSCRIPTS / "m4_finedge_pilot_scoping.txt").read_text("utf-8"))

    deck = _find(extraction, "pricing deck")
    dag = _find(extraction, "dag config")
    assert deck and dag, [c.text for c in extraction.commitments]
    assert deck[0].due_date == date(2026, 9, 3)
    assert dag[0].due_date == date(2026, 9, 5)
    for item in (deck[0], dag[0]):
        assert is_verbatim(item.source_quote, transcript)
    assert not any(f.kind == "commitment" for f in extraction.facts)


async def test_p2_m5_closes_dag_configs_not_the_deck() -> None:
    client = _client()
    m5 = await _extract(client, "m5_finedge_check_in.txt", "Check-in", "2026-09-15")
    assert m5.acknowledgements, "P1 found no acknowledgements in M5"
    open_commitments = (
        "cm_deck: Send revised pricing deck with pilot option\ncm_dag: Send sample DAG configs"
    )
    acks = "\n".join(
        f'{i}: {a.description} — "{a.source_quote}"' for i, a in enumerate(m5.acknowledgements)
    )
    prompt = render_prompt(
        "match_acknowledgements",
        open_commitments=open_commitments,
        meeting_date="2026-09-15",
        acknowledgements=acks,
    )
    matches = await client.complete_json(prompt, AckMatches, temperature=0.0)
    closed = {m.commitment_id for m in matches.closed}
    assert "cm_dag" in closed
    assert "cm_deck" not in closed
