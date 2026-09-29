# Meeting Prep Agent — Task Breakdown

Sep 28, 2026 · @Thomas

## How to use this breakdown

31 tickets in 6 phases; each ticket is one coding-agent session and one PR, and tickets in different lanes with met dependencies can run in parallel.

- **Lanes:** `BE-core` (ingest, memory, data), `BE-brief` (brief, reasoning, ask), `FE` (frontend), `DATA` (seed and evaluation). Up to four agents can work at once, one per lane.
- **Start rule:** a ticket starts only when every ticket in its "Depends on" column is merged.
- **Done rule:** the ticket's "Done when" column plus the Definition of done in the [Acceptance Criteria & Test Plan](https://claude.ai/code/artifact/124336a4-a6f4-42f2-a8e8-0a84e3528145).
- **Status:** tracked in the Status column below; update it when a PR opens and when it merges.

## Phases and gates

1. **Foundation (T01–T04).** Gate: `docker compose up` starts all three services; CI green on an empty app.
2. **Core data and memory (T05–T10).** Gate: the memory contract test passes and all 15 transcripts pass the validator. **Gate closed (2026-09-29).**
3. **Ingest and brief (T11–T15).** Gate: `make reset-demo` seeds everything through the real ingest path; the M6 brief via API contains B1, B3, B4 with citations; `no_memory` mode works. This is the minimum demoable product.
4. **UI (T16–T19).** Gate: the full P0 demo runs in the browser, including the toggle and style learning.
5. **P1 features (T20–T26).** Gate: G-1 to G-4 golden scenarios pass.
6. **Hardening and demo (T27–T31).** Gate: demo-readiness checklist complete; two rehearsals under 90 seconds.

If time runs short, cut from phase 5 in this order: T26 nudges, T25 stakeholder map and health, T22 patterns. Never cut T20 contradictions or T23–T24 Ask; they carry the memory story.

## Tickets

Feature numbers (F#) refer to the Feature spec; acceptance numbers match the Acceptance Criteria doc.

| ID | Task | Lane | Depends on | Key files | Done when | Status |
| --- | --- | --- | --- | --- | --- | --- |
| T01 | Backend scaffold: uv project, FastAPI app, `config.py` with `demo_today`, error handler, `/api/health` stub | BE-core | — | `backend/app/main.py`, `config.py`, `core/` | App starts; health returns 200; error shape matches schemas doc | Done |
| T02 | Docker Compose: hindsight (LLM provider via .env, stable worker id, volume), api, web; `.env.example` | BE-core | — | `docker-compose.yml`, `.env.example` | `docker compose up` brings up all three; Hindsight UI on 9999 | Done |
| T02b | `backend/Dockerfile` and `frontend/Dockerfile` | BE-core, FE | T01, T03 | `backend/Dockerfile`, `frontend/Dockerfile` | `docker compose build` and `docker compose up` bring up all three services (hindsight, api, web) cleanly | Done |
| T03 | Frontend scaffold: Vite, React, TS, Tailwind, shadcn/ui, router, layout, OpenAPI client script | FE | — | `frontend/src/`, `package.json` | Three empty routes render; `npm run gen:api` works | Done |
| T04 | AGENTS.md, hindsight-docs skill, CI (ruff, mypy, pytest, eslint, tsc) | BE-core | T01, T03 | `AGENTS.md`, `.github/workflows/ci.yml` | CI green on PR | Done |
| T05 | All Pydantic models and enums from Data Model & Schemas | BE-core | T01 | `app/schemas/*` | Models import; round-trip JSON tests pass | Done |
| T06 | SQLModel tables, repository, session, reset | BE-core | T05 | `app/db/*` | CRUD tests pass; overdue query uses `demo_today` | Done |
| T07 | `tags.py`, `memory_service.py` (bootstrap, retain, recall, reflect, mental models, wait\_until\_idle), `FakeMemoryService`, live contract test | BE-core | T02, T05 | `app/memory/*`, `tests/fakes/` | Contract test passes against real Hindsight | Done (live contract test passes on openai gpt-4.1-mini) |
| T08 | `llm/client.py` with provider adapters (openai, groq, anthropic): `complete_json` with retry on invalid JSON, timeouts, 429 backoff; `FakeLLM` | BE-brief | T01 | `app/llm/client.py` | Unit tests for retry and error mapping pass | Done |
| T08b | Switchable LLM provider (openai, groq, anthropic) via `.env` for the app and for Hindsight: config validation, `complete_json` + `complete_text` on all three adapters, `live_llm` smoke tests; re-run and un-skip T07's live contract test | BE-brief | T07, T08 | `app/llm/providers/*`, `app/llm/client.py`, `config.py`, `docker-compose.yml`, `.env.example` | Adapter unit tests pass with mocked HTTP; `live_llm` smoke test passes for each provider that has a key; T07's live contract test passes on Hindsight's configured provider | Done (live_llm openai passes; T07 live test passes) |
| T08c | Startup config validation: FastAPI lifespan hook calls `validate_llm_config()` for the app provider and checks `HINDSIGHT_LLM_PROVIDER`, `_MODEL` and `_API_KEY` are set and the provider is one of openai\|groq\|anthropic; plus T08b hardening: OpenAI temperature best-effort retry, explicit `httpx2` dev dependency, `.claude/worktrees/` in `.gitignore` | BE-core (hook), BE-brief (hardening) | T08b | `app/main.py` and its tests; `app/llm/providers/openai.py`, `pyproject.toml`, `.gitignore` | Startup fails fast naming the variable and never printing values; mocked-HTTP test for the OpenAI temperature retry passes | Done |
| T08d | **Low priority, run after the Phase 3 gate.** Anthropic adapter model support: before building, re-check the current Anthropic API docs for structured-output and `tool_choice` constraints per model; then support the newest models via `output_config.format` (no forced `tool_choice`) and older models via forced tool call plus `extra_body` temperature, or fail fast on unsupported model names | BE-brief | T08b | `app/llm/providers/anthropic.py`, tests | Documented per-model behavior; mocked-HTTP tests per path; `live_llm` smoke passes for Anthropic if a key is set | Not started |
| T08e | Optional `timeout_seconds` argument on `get_llm_client` (default unchanged at 30 s) so the offline transcript generator can use a longer timeout | BE-brief | T08b | `app/llm/client.py`, `tests/unit/test_llm_text_and_factory.py` | Default stays 30 s; unit test shows the value reaches each adapter | Done |
| T09 | Seed JSON: company, accounts, contacts, meetings, beats | DATA | — | `data/seed/*.json` | Matches Synthetic Data Spec tables exactly | Done |
| T10 | Generator (G1) and validator; generate 15 transcripts; draft M6 for team edit | DATA | T08, T09 | `data/scripts/generate.py`, `validate.py`, `transcripts/` | Validator passes all 15; M6 reviewed | Done |
| T11 | Seed script through the real ingest path; `make reset-demo` | DATA | T10, T12 | `data/scripts/seed.py`, `Makefile` | Reset completes; bank and DB populated | Done. Phase 3 gate passed with known deviations: brief p50 about 36-54 s (reflect step about 40 s), B3 cited to M4/M3, B4 not surfaced by P3 |
| T12 | Ingest service: P1 extraction, entity resolution, P2 ack matching, ledger, retain, jobs, learned summary | BE-core | T06, T07, T08 | `services/ingest.py`, prompts P1, P2 | Acceptance 1–3 pass on M4, M5 fixtures | Done. Phase 3 gate passed with known deviations: brief p50 about 36-54 s (reflect step about 40 s), B3 cited to M4/M3, B4 not surfaced by P3 |
| T13 | Meetings, notes and jobs API | BE-core | T12 | `api/meetings.py`, `api/jobs.py` | Endpoints match OpenAPI in schemas doc | Done. Phase 3 gate passed with known deviations: brief p50 about 36-54 s (reflect step about 40 s), B3 cited to M4/M3, B4 not surfaced by P3 |
| T14 | Brief service: evidence assembly, recall plan, mental model, P3, citation mapping, `no_memory` mode, cache | BE-brief | T06, T07, T08 | `services/brief.py`, prompt P3 | Acceptance 4–6 and 9 pass with fakes; phase 3 gate via API | Done: one critical; overdue commitments grouped; B4 code-built; live M6 check 43.1 s |
| T15 | Brief API (generate, get) | BE-brief | T14 | `api/briefs.py` | Endpoints match schemas doc | Done. Phase 3 gate passed with known deviations: brief p50 about 36-54 s (reflect step about 40 s), B3 cited to M4/M3, B4 not surfaced by P3 |
| T16 | Dashboard, LogNotesDialog, job polling, learned toast | FE | T03, T13 | `pages/Dashboard.tsx` | Acceptance 1 passes in browser | Done |
| T17 | Brief page: sections, severities, CitationChip, MemoryToggle side by side, personalization meter | FE | T03, T15 | `pages/Brief.tsx`, components | Acceptance 5, 9, 11 pass in browser | Done |
| T18 | Contact timeline API and page | FE | T07, T03 | `api/contacts.py`, `pages/ContactTimeline.tsx` | Acceptance 10 passes | Done |
| T19 | Feedback API, preferences service, style profile, FeedbackControls | BE-brief | T14, T17 | `services/preferences.py`, components | Acceptance 7–8 pass; phase 4 gate met | Done |
| T20 | Reasoning: R2 contradictions after ingest, account alerts | BE-core | T12 | `services/reasoning.py`, prompt R2 | Acceptance 12 passes | Not started |
| T21 | R1 objections and R3 cross-contact gaps in the brief | BE-brief | T14 | `services/brief.py`, prompts R1, R3 | Acceptance 13 passes | Not started |
| T22 | R4 cross-deal patterns in the brief | BE-brief | T14, T11 | prompt R4 | Acceptance 16 passes | Not started |
| T23 | Ask backend: R5, pin, Remember this, `ask_answers` | BE-brief | T06, T07 | `services/ask.py`, `api/ask.py` | Acceptance 18 (API parts) passes | Not started |
| T24 | AskPanel UI and P4 suggested questions | FE | T17, T23 | `components/AskPanel.tsx`, prompt P4 | Acceptance 18 passes in browser | Not started |
| T25 | Stakeholder map and relationship health | FE | T06, T18 | `api/accounts.py`, components | Acceptance 14–15 pass | Not started |
| T26 | Nudges API and digest | FE | T06, T16 | `api/nudges.py`, `NudgeDigest.tsx` | Acceptance 17 passes | Not started |
| T27 | Golden tests G-1 to G-4 in throwaway banks | DATA | T11, T20, T21, T22 | `tests/golden/` | All four pass; phase 5 gate met | Not started |
| T28 | Demo tooling: `demo-after-m6` snapshot, pre-generated briefs | DATA | T11 | `Makefile`, scripts | Snapshot restores in under 1 minute | Done: snapshot captured; restore dry-run/refusals tested; scratch Hindsight check skipped |
| T29 | AMI evaluation script (optional) | DATA | T12 | `data/scripts/eval_ami.py` | Recall and extraction scores reported | Not started |
| T30 | UI polish: loading, empty and error states, visual pass | FE | T17 | `frontend/src/` | Performance budgets met; no layout breaks | Not started |
| T31 | Demo script and rehearsals | DATA | T27, T28, T30 | `docs/demo-script.md` | Demo-readiness checklist complete | Not started |

## Ticket prompt template

Paste this into a coding agent to start a ticket; fill the braces from the ticket row. Keeping every session on the same template keeps agents from drifting.

```markdown
You are implementing ticket {ID}: {Task}.

Read first (in the repo's docs/ folder):
- AGENTS.md (rules)
- Technical design, Data Model & Schemas, Hindsight Integration Spec
- {extra docs for this ticket, e.g. Prompt Specs P1/P2, Synthetic Data Spec}

Scope:
- Files you may create or change: {Key files} and their tests.
- Do not change schemas, tag conventions or other modules' interfaces. If you
  believe one must change, stop and explain why instead of changing it.

Done when:
- {Done when}
- Plus the Definition of done in the Acceptance Criteria doc.

Workflow:
1. Summarise your plan in 5 bullets before writing code.
2. Write tests first for the acceptance criteria listed above.
3. Implement until tests, lint and type checks pass.
4. Report: what you built, test results, anything you could not do, and any
   doc that now needs updating.
```
