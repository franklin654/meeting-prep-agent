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
| B1 | complete | `92b545b` |
| B2 | complete | `621b7cc` |
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
| App LLM | 20 logical P1 calls (19 completed + 1 earlier interrupted), 1 P2 | partial: 3,442 | partial: 1,485 | The 15-call A3 backfill and two original Sandbox-W previews have no recoverable usage records. Logging fix was demonstrated with a Sandbox-W Uvicorn P1+P2 and one isolated one-meeting backfill-script P1; their provider totals are 3,442 prompt / 1,485 completion tokens. Four temperature fallbacks succeeded (A3, first Sandbox-W preview, Uvicorn probe, script probe); one earlier interrupted call had its retry interrupted. |
| Hindsight retain | 3 attempts (2 reached service and completed; 1 connection-refused before a write) | unavailable | unavailable | The two accepted writes are both in `ae-overhaul-test`, at the original cap; the refused attempt never reached Hindsight. |
| Hindsight reflect | 0 | — | — | — |
| Brief generation | 0 | — | — | — |
| Pattern refresh | 0 | — | — | — |

## A3 backfill completion

- Confirmed `/home/saisivakesh/meeting-prep-backups/app.db.pre-overhaul` exists and passes `PRAGMA integrity_check`; the backfill client uses `timeout_seconds=120`, matching ingest. Backfill dry-run found 15 eligible meetings with zero calls.
- Detached sequential real-DB backfill completed: 15 P1 calls, 15 meetings processed, 133 verified facts (`deal_fact:89`, `objection:26`, `personal:15`, `competitor:3`); all 15 meetings have at least two facts. Per-meeting counts are in the ignored log `artifacts/overhaul/a3-facts-backfill.log`. One expected `gpt-6-luna` temperature rejection was retried without temperature and succeeded. No Hindsight calls occurred.
- Token totals for the original real-DB run are unavailable: A0 usage records went through a module logger that was not visible in the normal Uvicorn logger configuration. Do not rerun the real backfill solely to recover these counts.
- A3 checks: 127 tests passed; Ruff and mypy passed. The requested fact-kind per-meeting tally was added to the script output.
- Read-only real-DB audit against `/home/saisivakesh/meeting-prep-backups/app.db.pre-overhaul`: both DBs pass `PRAGMA integrity_check`; current DB added exactly `capturedraft`, `extractedfact`, `meetingprepared`, and `memoryoverride`; no existing table schema or row hashes changed. `extractedfact` has 133 rows; the other three new tables are empty. Backup/current both have 17 meetings, 33 commitments (7 done, 26 open), and 0 feedback rows. Cached brief JSON hashes are unchanged: `br_ae8ce076` SHA-256 `e20dbc69ff717ee83ecb71fc07c91c3292365e234b5d0e2c99fa4c29ad5918d0`; `br_07e16a63` SHA-256 `b29b896ef3a89fd1f9fa71a148b59b8495dff4dfa27db16b94d22158391c949e`.

| Meeting | Title | Facts by kind | Total |
| --- | --- | --- | ---: |
| `n1_nimbus` | Discovery | deal_fact 8; objection 3; personal 2 | 13 |
| `n2_nimbus` | Security review | deal_fact 2; objection 1; personal 1 | 4 |
| `n3_nimbus` | Security follow-up | deal_fact 6; objection 1; personal 1 | 8 |
| `o1_orbit` | Discovery | deal_fact 4; objection 2; personal 2 | 8 |
| `n4_nimbus` | Contract and kickoff | deal_fact 7; objection 3 | 10 |
| `o2_orbit` | Pricing | competitor 1; deal_fact 3; objection 1 | 5 |
| `m1_finedge` | Discovery | deal_fact 4; objection 2; personal 1 | 7 |
| `m2_finedge` | Budget and process | deal_fact 8; objection 4; personal 1 | 13 |
| `o3_orbit` | Decision | competitor 1; deal_fact 8; personal 1 | 10 |
| `m3_finedge` | Technical deep dive | competitor 1; deal_fact 4; objection 3; personal 1 | 9 |
| `v1_veda` | Discovery | deal_fact 9; objection 1 | 10 |
| `m4_finedge` | Pilot scoping | deal_fact 9; objection 1; personal 1 | 11 |
| `v2_veda` | Technical review | deal_fact 5; objection 2; personal 2 | 9 |
| `m5_finedge` | Check-in | deal_fact 5; objection 1; personal 1 | 7 |
| `v3_veda` | Sandbox check-in | deal_fact 7; objection 1; personal 1 | 9 |

All 15 fact-bearing meetings have at least 2 facts (133 total). The audit used SQLite URI `mode=ro`; no writes were made.
- Created `backend/app.sandbox.db` and `backend/app.sandbox-r.db` using SQLite's online backup command from the completed real DB; both pass `PRAGMA integrity_check`. Both paths are ignored by Git.
- A4: added `POST /api/meetings/{meeting_id}/capture/preview`, `POST /api/capture/{draft_id}/save`, and `DELETE /api/capture/{draft_id}`. Preview runs P1 and conditional P2, writes only the capture draft/job, validates quotes, and annotates duplicates, closes, and due-date renewals. Save applies checked items, retains the transcript without rerunning P1/P2, and is idempotent; discard leaves the ledger and memory untouched. `JobStatus` now carries a draft response. Offline `app.openapi()` generation updated the frontend API client to 20 paths. No new DB table or application error code.
- A4 checks: plain pytest 678 passed, 1 skipped, 6 deselected; Ruff and mypy passed. Capture API tests cover preview isolation, selected-only save, no second extraction, save idempotency, discard, transcript length, duplicate and renewal badges. No live LLM or Hindsight calls in A4.
- A5: replaced the horizontal header navigation with the 216px desktop sidebar, responsive mobile navigation, title/action top bar, and health-backed AE/company footer. Centralized the wireframe's warm neutrals and teal memory accent, switched to locally bundled IBM Plex Sans/Mono, and aligned shared buttons/cards to the requested minimum target sizing and 10px shape. Added navigable placeholders for /contacts, /ask, /capture and /memory; preserved /meetings/:id and /contacts/:id. The two `@fontsource` dependencies are added because the UI spec requires bundled fonts to work offline.
- A5 checks: frontend lint and TS typecheck passed; 47 Vitest tests passed; production build passed (Vite reports the existing main JS chunk at 533 kB, slightly above its 500 kB advisory threshold). No live calls.
- A6: rebuilt Today with client-side meeting/contact search, responsive upcoming cards and their brief/history/follow-up chips, first-meeting generic-brief note, and a nudge/style right rail with explicit loading, empty, and error states. Added scheduling dialog for existing/new accounts, account-scoped attendees and inline contact creation; date minimum and validation use `/api/health.demo_today`. The old log-notes flow remains available, and the header's “Add meeting notes” action routes to Capture. No endpoint/schema change and no live calls.
- A6 checks: lint, typecheck, and production build passed; 49 Vitest tests passed, including client-side search and create-account/contact/schedule flow. Vite main JS chunk is 546 kB, with its 500 kB advisory warning.
- A7: replaced the Capture placeholder with Paste → Review → Saved, newest-first upcoming/recent meeting selection, 50–200,000 character validation, in-browser `.txt`/`.md` upload (no voice notes), preview/save job polling, quote-backed review items, badges, discard, readable job errors, and links to the saved brief/contact. The review explicitly explains that unchecking removes only ledger/fact entries while the transcript is still remembered. Fixed save selection so a checked duplicate can be re-selected; backend regression test covers that path. No endpoint or schema addition.
- A7 / Checkpoint 1 gates: backend Ruff and mypy passed; plain pytest 678 passed, 1 skipped, 6 deselected. Frontend lint and typecheck passed; 52 Vitest tests passed; production build passed with the Vite main chunk advisory (560 kB).
- Checkpoint 1 Sandbox-W validation: overrides were verified without reading `.env`; API is isolated on `127.0.0.1:8001` using `backend/app.sandbox.db`, `DEMO_USER_ID=overhaul-test`, `MEMORY_READ_ONLY=false`; Vite is on `127.0.0.1:5174` proxying to :8001. Hindsight bank is `ae-overhaul-test`. Both sandbox DB integrity checks passed. API and Vite remain running; the real-DB API on :8000 was never started.
- Created synthetic account `acc_417a493e` / Morgan Riley `c_0da3f365`; meeting `m_c2266acc` appeared in the Upcoming list before capture. First P1 preview produced 1 commitment and 3 facts. Its save hit a startup race (`Retain failed: Cannot connect to host localhost:8888`); the failed job `job_35bf1f0b` committed its ledger/facts before retain and remains as a sandbox-only record. Hindsight then reported healthy. A fresh synthetic meeting `m_c50d663c` was prepared and previewed; duplicate detection found the earlier saved commitment/fact, and the unchecked duplicate was omitted. Save job `job_67eafd09` completed with 1 retain to Hindsight. Verified the retry meeting is done/prepared, Morgan's contact reports 2 meetings/1 open follow-up, and SQLite contains the expected commitment and fact rows for both sandbox meetings. The new account's meeting appeared in Today/Upcoming before capture; after successful capture it is in Done/recent.
- Playwright/browser automation is unavailable in this session. Manual UI checklist: open `http://127.0.0.1:5174`; on Today, search for “AE Overhaul Checkpoint 1” and confirm the still-upcoming “Checkpoint 1 Capture Review” appears; in Contacts, search Morgan Riley; in Capture, select “Checkpoint 1 Capture Review Retry” from recent meetings and confirm the Saved summary and brief/contact actions. The API/ledger checks above confirm the corresponding data. No screenshots were fabricated.
- Live calls through Checkpoint 1: A3's 15 completed backfill P1 calls plus the earlier interrupted logical call; 2 Sandbox-W P1 previews (both completed); 2 retain attempts (one connection failure before service acceptance, one successful retain). No brief generation, pattern refresh, or Hindsight reflect has run. Token totals remain unavailable from provider responses/logs; app logs did not expose provider-reported usage. The earlier expected `gpt-6-luna` temperature rejection retried successfully in the first Sandbox-W preview.
- A0 logging fix: root cause was `BaseProvider` logging `llm.usage` on `app.llm.providers.base`; normal Uvicorn INFO handling is explicitly configured on `uvicorn.error` (the same logger used by brief timing). Changed the usage logger and strengthened adapter tests to assert logger name/level, provider token values, and no prompt/key leakage. Verification lines: Uvicorn `INFO:     llm.usage provider=openai model=gpt-6-luna call_type=json prompt_tokens=1476 completion_tokens=643`; P2 in the same probe reported 542/83. Standalone `backfill_facts.py` on a one-meeting temporary SQLite DB emitted `llm.usage provider=openai model=gpt-6-luna call_type=json prompt_tokens=1424 completion_tokens=759`. A3's historical token totals remain unknown; its original log has no usage lines, so no real-DB rerun was made.
- Failed-save recovery checks: full backend pytest 679 passed, 1 skipped, 6 deselected; frontend Vitest 53 passed; Ruff, mypy, lint, and TypeScript check passed.
- Ignore verification: `backend/app.sandbox*.db` and `artifacts/` both match `git check-ignore`; `backend/app.sandbox.db`, `backend/app.sandbox-r.db`, and the A3 log are not tracked. Added the wildcard because the prior patterns named only the two copies. The unrelated pre-existing `deliverables/` line was shown to the user and remains unstaged/uncommitted.

### B1 implementation

- Added backward-compatible `Brief` enrichment fields: `you_owe`, `they_owe`, ranked fact-backed objections, `memory_used`, contact cards, and `first_meeting`; regenerated the frontend API client offline from `app.openapi()` (20 paths). No table or endpoint changed.
- Commitment cards are SQLite-ledger sourced and carry meeting-title/date citations with quote fallback to the commitment text. One oldest us-owned overdue commitment is critical; other overdue obligations are warnings. Enriched obligations replace the duplicate P3 open-commitments section. Fact objections cluster by text overlap, count distinct source meetings, rank by frequency/recency, and include citations; they replace duplicate P3 objections. Hidden fact and memory overrides are excluded from their respective brief sources.
- Contact cards show account, role, recent meeting citations, follow-up counts, and only show a communication-style line when a personal fact explicitly contains a preference cue; that line cites its source. A first memory brief with no earlier completed account meeting skips Hindsight reads and ledger/fact/override reads while still making the normal single P3 call with an empty evidence table; the UI labels it “No history yet”.
- B1 checks: backend 683 passed, 1 skipped, 6 deselected; Ruff and mypy passed; frontend lint/typecheck and 53 Vitest tests passed; production build passed (existing >500 kB bundle advisory). New tests cover enrichment, first-meeting no-memory retrieval, hidden-source filtering, contact-style citations, and legacy cached brief payload rendering. No live LLM or Hindsight calls and no real DB reads/writes for B1.
- B2: added deterministic `they_owe_overdue` and `no_history` nudge kinds with the specified priority order and eight-row cap. Added `POST /api/style/reset` and `DELETE /api/style/rules/{section}`; both delete only SQLite feedback, return the recomputed profile, and make no Hindsight call. Updated the typed nudge UI tones, documented the changed schema/routes, and regenerated the client offline from `app.openapi()` (22 paths).
- B2 checks: backend 686 passed, 1 skipped, 6 deselected; Ruff and mypy passed; frontend lint/typecheck and 53 Vitest tests passed. Tests cover priority/cap, closed-account exclusion, the two style deletion semantics, and both new nudge kinds as links. No live LLM/Hindsight calls or real DB operations.

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
