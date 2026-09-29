# UI overhaul notes

## Status

| Ticket | Status | Commit |
| --- | --- | --- |
| Stage 0 | complete | `d185960` |
| A0 | complete | implementation `3f667b1` |
| A1 | complete | implementation `ecd34d9` |
| A2 | complete | `f5f7585` |
| A3 | complete | `4599067` |
| A4 | complete | implementation `532f731` |
| A5 | complete | implementation `dc12c17` |
| A6 | complete | implementation `2b59262` |
| A7 | complete | implementation `5a95eb5` |
| B1 | planned | — |
| B2 | planned | — |
| B3 | planned | — |
| B4 | planned | — |
| B5 | planned | — |
| C1 | planned | — |
| C2 | planned | — |
| C3 | planned | — |
| C4 | planned | — |

## Decisions and safeguards

- Stage 0 backup: `/home/saisivakesh/meeting-prep-backups/app.db.pre-overhaul`, SQLite `integrity_check` passed.
- Tag: `pre-ui-overhaul` at `459f871`.
- Leave `deliverables/` untracked. Never read, edit, or commit `.env`; never use the real-DB API on port 8000.
- The current server was unavailable during Stage 0. The checked-in generated OpenAPI client is the baseline contract until offline generation is run.
- Per the user's explicit resolution of the conflict with AGENTS.md rule 9, commits that change a schema, table, endpoint, or error code may update only the matching portions of `docs/data-model-and-schemas.md`; all other conflicts belong in this file.
- A0: `MEMORY_READ_ONLY` defaults off. The real and fake memory gateways reject every write (`ensure_bank`, `ensure_mental_models`, meeting/note/preference retains) with `memory_read_only` before issuing an SDK call. Provider adapters now log provider, model, `json`/`text` call type, and provider-reported prompt/completion token counts only.
- A1: Added only the requested additive tables (`extractedfact`, `capturedraft`, `meetingprepared`, `memoryoverride`) and their repository gateways. No `create_all` call was run against `backend/app.db`.
- A2: Added account/contact creation and listing, meeting scheduling/cancellation, prepared markers, and enriched meeting summary metrics. Added `ae_name` and `company_name` to health using the seeded company file; Docker API mounts `./data` read-only at `/data` for the same source. Regenerated `frontend/src/api/schema.d.ts` offline from `app.openapi()` (17 paths). No new error codes.
- A3: Ingestion persists quote-verified P1 facts and replaces a meeting's facts on re-ingest; fact contacts are matched with the existing resolver. Added a sequential resumable P1-only `data/scripts/backfill_facts.py` with `--dry-run` and `--limit`. No prompt files changed.

## Live-call and token tally

| Operation | Calls | Prompt tokens | Completion tokens | Notes |
| --- | ---: | ---: | ---: | --- |
| App LLM | 16 attempts (15 completed + 1 earlier interrupted) | unavailable | unavailable | Backfill's INFO usage records were suppressed by the standalone script's default logging level; fixed the script to enable INFO for future runs. One expected temperature fallback, retry succeeded. |
| Hindsight retain | 0 | — | — | — |
| Hindsight reflect | 0 | — | — | — |
| Brief generation | 0 | — | — | — |
| Pattern refresh | 0 | — | — | — |

## A3 backfill completion

- Confirmed `/home/saisivakesh/meeting-prep-backups/app.db.pre-overhaul` exists and passes `PRAGMA integrity_check`; the backfill client uses `timeout_seconds=120`, matching ingest. Backfill dry-run found 15 eligible meetings with zero calls.
- Detached sequential real-DB backfill completed: 15 P1 calls, 15 meetings processed, 133 verified facts (`deal_fact:89`, `objection:26`, `personal:15`, `competitor:3`); all 15 meetings have at least two facts. Per-meeting counts are in the ignored log `artifacts/overhaul/a3-facts-backfill.log`. One expected `gpt-6-luna` temperature rejection was retried without temperature and succeeded. No Hindsight calls occurred.
- Token totals are unavailable: A0 usage logging is INFO-level, but the standalone script had no INFO logging configuration, so the run log captured only the temperature warning and final summary. The script now enables INFO logging for future runs; do not rerun the real backfill solely to recover these counts.
- A3 checks: 127 tests passed; Ruff and mypy passed. The requested fact-kind per-meeting tally was added to the script output.
- Created `backend/app.sandbox.db` and `backend/app.sandbox-r.db` using SQLite's online backup command from the completed real DB; both pass `PRAGMA integrity_check`. Both paths are ignored by Git.
- A4: added `POST /api/meetings/{meeting_id}/capture/preview`, `POST /api/capture/{draft_id}/save`, and `DELETE /api/capture/{draft_id}`. Preview runs P1 and conditional P2, writes only the capture draft/job, validates quotes, and annotates duplicates, closes, and due-date renewals. Save applies checked items, retains the transcript without rerunning P1/P2, and is idempotent; discard leaves the ledger and memory untouched. `JobStatus` now carries a draft response. Offline `app.openapi()` generation updated the frontend API client to 20 paths. No new DB table or application error code.
- A4 checks: plain pytest 678 passed, 1 skipped, 6 deselected; Ruff and mypy passed. Capture API tests cover preview isolation, selected-only save, no second extraction, save idempotency, discard, transcript length, duplicate and renewal badges. No live LLM or Hindsight calls in A4.
- A5: replaced the horizontal header navigation with the 216px desktop sidebar, responsive mobile navigation, title/action top bar, and health-backed AE/company footer. Centralized the wireframe's warm neutrals and teal memory accent, switched to locally bundled IBM Plex Sans/Mono, and aligned shared buttons/cards to the requested minimum target sizing and 10px shape. Added navigable placeholders for /contacts, /ask, /capture and /memory; preserved /meetings/:id and /contacts/:id. The two `@fontsource` dependencies are added because the UI spec requires bundled fonts to work offline.
- A5 checks: frontend lint and TS typecheck passed; 47 Vitest tests passed; production build passed (Vite reports the existing main JS chunk at 533 kB, slightly above its 500 kB advisory threshold). No live calls.
- A6: rebuilt Today with client-side meeting/contact search, responsive upcoming cards and their brief/history/follow-up chips, first-meeting generic-brief note, and a nudge/style right rail with explicit loading, empty, and error states. Added scheduling dialog for existing/new accounts, account-scoped attendees and inline contact creation; date minimum and validation use `/api/health.demo_today`. The old log-notes flow remains available, and the header's “Add meeting notes” action routes to Capture. No endpoint/schema change and no live calls.
- A6 checks: lint, typecheck, and production build passed; 49 Vitest tests passed, including client-side search and create-account/contact/schedule flow. Vite main JS chunk is 546 kB, with its 500 kB advisory warning.
- A7: replaced the Capture placeholder with Paste → Review → Saved, newest-first upcoming/recent meeting selection, 50–200,000 character validation, in-browser `.txt`/`.md` upload (no voice notes), preview/save job polling, quote-backed review items, badges, discard, readable job errors, and links to the saved brief/contact. The review explicitly explains that unchecking removes only ledger/fact entries while the transcript is still remembered. Fixed save selection so a checked duplicate can be re-selected; backend regression test covers that path. No endpoint or schema addition.
- A7 / Checkpoint 1 gates: backend Ruff and mypy passed; plain pytest 678 passed, 1 skipped, 6 deselected. Frontend lint and typecheck passed; 52 Vitest tests passed; production build passed with the Vite main chunk advisory (560 kB). No live calls have been made for A7 or Checkpoint 1 yet.

## B4–C4 plan addendum

| Ticket | Primary files | Endpoint/model additions | Main risks |
| --- | --- | --- | --- |
| B4 | `api/contacts.py`, new `api/memories.py`, new `api/commitments.py`, `services/profile.py`, `services/ask.py`, `services/brief.py`, `db/facts_repo.py`, `db/overrides_repo.py`, `db/commitments_repo.py`, `schemas/api.py`, `schemas/patterns.py`, `llm/prompts/derive_patterns.md`, tests | `GET /api/contacts/{id}/profile`; `POST/DELETE /api/memories/{id}/hide`; `POST /api/memories/{id}/correct`; `PATCH/DELETE /api/commitments/{id}`; `POST /api/contacts/{id}/patterns/refresh`; `ContactProfile`, `MemoryOverride`, `ContactPattern` | Overrides must consistently filter profile, brief evidence, and Ask without claiming to delete a Hindsight memory. Pattern output must validate fact ids and never run automatically. |
| B5 | `pages/Contacts.tsx`, `pages/ContactProfile.tsx`, `components/*`, `api/hooks.ts`, `api/keys.ts`, `routes.tsx`, UI tests | consumes B4 contracts | Confirmed destructive follow-up operations; source chips must use title plus date, never ids. |
| C1 | `pages/Ask.tsx`, `components/AskPanel.tsx`, routes, hooks, UI tests | no new backend contract expected | Scope changes cannot leak account context; preserve the existing drawer and in-memory three-turn history. |
| C2 | new `api/memory.py`, `services/memory_overview.py`, `db/facts_repo.py`, `memory/memory_service.py`, `schemas/api.py`, `pages/Memory.tsx`, hooks/tests | `GET /api/memory/overview`; `MemoryOverview` | Hindsight statistics must be read-only, short-timeout, and nullable on failure; chart uses only real SQLite data. |
| C3 | all affected pages/components, `index.css`, responsive/accessibility tests | none | Keep 4.5:1 contrast, keyboard access, and three target widths without new client storage. |
| C4 | verification scripts/tests only; `docs/ui-overhaul-notes.md` | none | Do not exceed the live-call budget or write to real Hindsight outside the authorized pattern refreshes; backup only after verification. |

## Planned Checkpoint 2 evidence

- Sandbox-W: one first-meeting P3 brief, one pattern refresh, fact hide/correct, follow-up edit/delete, prepared state.
- Sandbox-R: at most two M6 memory brief generations, record latency/recall timeouts/critical count and verify read-only Hindsight behavior.
- Read cached M6 on the real-memory data path before generation to prove zero-call enrichment.
