# Meeting Prep Agent — Acceptance Criteria & Test Plan

Sep 28, 2026 · @Thomas

Feature numbers match the [Feature spec](https://claude.ai/code/artifact/a88c5f23-38e8-43fe-a34f-7c4a0b485693); fixture facts come from the [Synthetic Data Spec](https://claude.ai/code/artifact/73444de8-7dd7-4429-9beb-832c8da71d9c).

## Definition of done

A task is done only when every box below is true; an agent saying "implemented" is not evidence.

- [ ] Acceptance criteria for the feature (below) are met and each has a test
- [ ] Unit tests pass with `FakeMemoryService` and `FakeLLM`
- [ ] `ruff`, `mypy`, `eslint`, `tsc --noEmit` pass
- [ ] New or changed models match Data Model & Schemas; docs updated in the same PR
- [ ] No new direct import of `hindsight_client` or DB sessions outside their gateway modules
- [ ] Golden scenarios still pass (run on `main` after merge)
- [ ] Screenshot or short clip attached for any UI change

## P0 acceptance criteria

Each criterion is phrased as an observable check using the FinEdge fixture.

| # | Feature | Acceptance criteria |
| --- | --- | --- |
| 1 | Post-meeting capture | Pasting M6 into LogNotesDialog returns `202` in under 1 s; job reaches `done` in under 90 s; toast lists learned facts |
| 2 | Structured extraction | M4 yields 2 commitments (deck due 2026-09-03, DAG configs due 2026-09-05) with verbatim `source_quote`s; no commitment in `facts` |
| 3 | Entity resolution | "KS" in any transcript resolves to `c_karan`; an unknown speaker creates a contact with `needs_review=true` |
| 4 | One-click brief | M6 brief returns all sections in under 20 s; sections follow the style profile order |
| 5 | Citations | Every item in a `memory` brief has at least one citation with a meeting label; clicking it shows the source quote |
| 6 | Missed follow-ups | M6 brief shows the pricing deck as `critical`, cited to M4; DAG configs, SOC 2 report, ROI one-pager and case study do not appear as open |
| 7 | Style adaptation | Collapsing personal touchpoints twice hides it in the next brief for any account; a toast confirms the learned preference |
| 8 | Feedback loop | Each feedback action stores a `Feedback` row and retains one `kind:preference` sentence |
| 9 | With/without toggle | `no_memory` M6 brief has zero citations and none of the six beats; `memory` brief has all pre-M6 beats (B1, B3–B6) |
| 10 | Memory inspector | Anita's timeline lists M2 facts (budget, half marathon) newest first, each linked to its meeting |
| 11 | Learning curve | Personalization meter shows `facts_used` and `preferences_applied`; values increase between a first-meeting brief and the M6 brief |

## P1 acceptance criteria

P1 features are judged on the same fixture; each maps to a story beat or a supporting account.

| # | Feature | Acceptance criteria |
| --- | --- | --- |
| 12 | Contradiction detection | After live M6 ingest, an account alert reads budget $40K (Jul 28) → $75K (Sep 29), cited to M2 and M6; no false contradiction for unchanged facts |
| 13 | Cross-contact intelligence | Pre-M6 brief alert names Sneha's SOC 2 / data-residency concern and Anita as not having heard it, cited to M3 and M5 |
| 14 | Stakeholder map | FinEdge shows Rahul (technical decision maker), Anita (economic buyer), Karan (champion), Sneha (security), Vikram (not yet met) |
| 15 | Relationship health | FinEdge health shows 3 of our 4 promises kept, 1 overdue, and their 1 promise kept; Orbit shows closed lost |
| 16 | Pattern learning | Veda V4 brief cites Nimbus N3 with "trust portal and pen-test summary" as what resolved the SOC 2 objection |
| 17 | Proactive nudges | Nudge digest on `DEMO_TODAY` lists the overdue deck, briefs ready for M6 and V4, and any contact silent for more than 21 days |
| 18 | Ask panel | "What did Anita say about budget?" returns a grounded answer citing M2; "What is Rahul's favourite food?" returns "Nothing in memory covers that yet."; a follow-up ("and when?") uses history; Pin adds a "Your questions" section; Remember this retains a `kind:note` memory |

## Golden scenarios

Four end-to-end tests against real Hindsight and the configured LLM providers, each in a throwaway bank; together they are the demo, run as tests.

1. **G-1 Pre-meeting brief (FinEdge M6).** Seed M1–M5 and supporting accounts → wait until idle → generate M6 brief. Assert B1 (overdue deck, critical), B2 pre-state (budget about $40K cited to M2), B3 (Ananya touchpoint), B4 (DataHawk watch-out), B5 (Anita gap), B6 is absent here (it belongs to Veda). Assert zero uncited items.
2. **G-2 Without memory.** Same meeting in `no_memory` mode. Assert none of "pricing deck", "Ananya", "DataHawk", "40K" appear.
3. **G-3 Live update.** Ingest M6 → wait until idle. Assert the budget contradiction alert; deck commitment still open with due date 2026-10-01; new commitments for Vikram intro (Oct 6) and pilot start (Oct 15); Anita's timeline has Sep 29 entries.
4. **G-4 Cross-deal pattern (Veda V4).** Generate V4 brief. Assert a pattern citing Nimbus N3.

Golden tests allow wording to vary: they assert on citations, severities, IDs, dates and a few key terms, never on full sentences.

## Test levels, budgets and demo readiness

| Level | Scope | Runs | Tools |
| --- | --- | --- | --- |
| Unit | Services, tags, schemas, post-processing | Every PR, CI | pytest, fakes |
| Prompt fixtures | P1–P4, R1–R5 on fixture inputs | On prompt change | pytest, live configured provider |
| Live LLM | One smoke call per provider through the client | On adapter change, before demo | pytest `-m live_llm`; skipped without that provider's key |
| Contract | Hindsight SDK round trip | On SDK bump | pytest `-m live` |
| Golden | G-1 to G-4 | Merge to `main`, before rehearsals | pytest `-m golden` |
| Validation (optional) | AMI recall and extraction scores | Once, for the pitch | `eval_ami.py` |
| UI | Brief rendering, toggle, Ask panel | Every PR | Vitest + manual clip |

**Performance budgets (local, demo machine):** dashboard load under 1 s; brief under 20 s (cached re-open under 1 s); Ask answer under 15 s; M6 ingest job under 90 s.

### Demo-readiness checklist

- [ ] `make reset-demo` completes and G-1 to G-4 pass on the demo laptop
- [ ] `DEMO_TODAY=2026-09-28` set; dashboard shows M6 and V4 as upcoming
- [ ] Briefs for M6 (both modes) and V4 pre-generated and cached
- [ ] `make demo-after-m6` snapshot exists and restores in under 1 minute
- [ ] LLM quota checked on the morning of the demo, for both the app's provider and Hindsight's provider
- [ ] Provider switching verified: each provider with a key passes the P1 fixture and returns a valid `BriefDraft`; an unknown provider or a missing key stops startup naming the variable, and no key is printed
- [ ] Two full rehearsals timed under 90 seconds
- [ ] Hindsight UI on port 9999 open in a spare tab as a backup memory view
