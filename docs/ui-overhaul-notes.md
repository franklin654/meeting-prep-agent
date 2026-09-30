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
| B1 | complete | `9dc5992` |
| B2 | complete | `3f32451` |
| B3 | complete | `2cc2f06` |
| B4 | complete | `27c69a0` |
| B5 | complete | `f341ef0` |
| Sandbox guard | complete | committed |
| First-meeting brief | complete | committed |
| C0 | complete | `4ac0226` |
| C1 | complete | `f0cc234` |
| C2 | complete | `11a195a` |
| C3 | complete | `46dd72c` |
| C4 | complete | `af7103c` + final handover commit |

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
| App LLM | 20 logical P1 calls (19 completed + 1 earlier interrupted), 1 P2, 5 P3, 1 pattern refresh = 27 logical calls | partial total: 8,101 | partial total: 7,207 | Existing 3,442/1,485 probe totals plus the checkpoint calls below. The 15-call A3 backfill and two original Sandbox-W previews remain unknown. Five current temperature fallbacks succeeded. |
| Hindsight retain | 3 attempts (2 reached service and completed; 1 connection-refused before a write) | unavailable | unavailable | The two accepted writes are both in `ae-overhaul-test`, at the original cap; the refused attempt never reached Hindsight. |
| Hindsight reflect | 0 | — | — | — |
| Brief generation | 5 total (3 Sandbox-W first-meeting calls, 2 Sandbox-R; one Sandbox-R run used the wrong bank and is not valid gate evidence) | 4,443 | 5,682 | P3 calls only; the two latest Sandbox-W checks are broken down below. |
| Pattern refresh | 1 Sandbox-W | 216 | 40 | Returned no cited patterns. |

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
- B3: rebuilt the brief header with a Today/account breadcrumb, meeting title/time, Regenerate/Generate confirmation, and Mark as prepared. Main content now orders where-left-off, owed ledger items, ranked objections, suggested plan, and remaining sections; critical ledger obligations also appear in Needs attention. The right rail shows attendee cards with fact-backed style citations, recent meeting source chips, follow-up counts, contact Ask actions, Full history links, and Memory used. Preserved mode toggle, side-by-side view, counters, citation popovers, section feedback, and old cached brief section fallbacks. Added `contact_id` to `ContactCard`; updated the schema doc and regenerated the client offline (22 paths).
- B3 checks: backend 686 passed, 1 skipped, 6 deselected; Ruff and mypy passed. Frontend lint/typecheck passed; 54 Vitest tests passed; production build passed (existing >500 kB chunk advisory). UI tests cover the new layout, prepared action, Ask rail, legacy cache payloads, feedback, and side-by-side mode. No live LLM/Hindsight calls or real DB operations.

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

### B4 implementation

- Added SQLite-backed contact profile data (facts/preferences, grouped meeting timeline, follow-ups, cached patterns, hidden count), app-side hide/unhide/correct overrides, commitment patch/delete, and explicit pattern refresh. Pattern refresh uses at most 40 visible facts, makes one app LLM call only when at least three facts exist, validates cited fact IDs and caches up to four results. Added the strict pattern prompt/schema and the `ContactPatternCache` table; updated the schemas document and generated the OpenAPI client offline (27 paths).
- Hidden memory IDs are filtered from brief Hindsight evidence and Ask citations; hidden/corrected extracted facts are excluded from profiles, brief-enrichment evidence, and matching Ask sources. The UI text explicitly says the original remains in Hindsight. Hindsight memory deletion is not claimed or attempted.
- B4 checks: backend 694 passed, 1 skipped, 6 deselected; Ruff and mypy passed. Profile/control/pattern tests use the temporary SQLite fixture, FakeLLM and FakeMemoryService; no live LLM, Hindsight, or real-DB operations.
- B4 live correction was not attempted: the previously authorized successful Hindsight retain cap is already consumed. Sandbox-W correction would be a third successful retain. This is carried as a checkpoint gate blocker unless separately authorized; do not treat a fake-service test as live confirmation.

### B5 implementation

- Replaced the Contacts placeholder with a searchable, account-filtered contact list and a profile view with Timeline, Facts, Follow-ups, and Preferences tabs. Added cited meeting links, explicit correct/hide controls and Hindsight-retention disclosure, follow-up complete/edit-date/delete actions with confirmation, cached pattern refresh (only when at least three facts exist), and the existing scoped Ask drawer.
- B5 checks: frontend ESLint and TypeScript passed; Vitest 54 passed. The running Sandbox-W services answer on API :8001 and Vite :5174; API health reports `ok`, Vite responds HTTP 200.

### Checkpoint 2 execution (2026-09-30)

- Sandbox-W first-meeting brief `m1_finedge`: one P3 call, 7.59 s, 573 prompt / 629 completion tokens; expected temperature fallback succeeded. It returned `first_meeting=true` and zero memory use, but P3 generated no sections, so the service correctly did not cache it. No retry (the authorized one-call gate is spent).
- Sandbox-W pattern refresh for Anita (7 visible facts): one call, 2.05 s, 216 / 40 tokens; returned no valid/cited patterns. No retry (the one-refresh gate is spent).
- Sandbox-W app-side controls passed: hid `fact_787e66e5` (profile then showed 1 hidden item), patched `cm_f299e8a3`, deleted `cm_83506182`, and marked `m6_finedge` prepared. Correction was deliberately not run live: both authorized successful Hindsight retains are already consumed; a further correct-note retain would exceed the user's cap. Its endpoint behavior has FakeMemory/unit coverage only, not live evidence.
- Sandbox-R was initially launched with the wrong `DEMO_USER_ID=overhaul-test`, targeting `ae-overhaul-test`. One read-only M6 generation ran there (13.33 s; 721 / 1,372 tokens). This was an operator configuration mistake, not valid real-bank evidence. It was not a write. The instance was corrected to `DEMO_USER_ID=user-demo-thomas`, `DATABASE_URL=sqlite:///./app.sandbox-r.db`, `MEMORY_READ_ONLY=true`; the expected bank is `ae-user-demo-thomas`.
- With the corrected Sandbox-R, cached `GET /api/meetings/m6_finedge/brief?mode=memory` before generation took 70 ms and returned `br_ae8ce076` with SQLite enrichment: 47 facts across 5 meetings, 5 You owe, 6 They owe, 5 ranked objections, 3 contact cards, one critical item (the pricing deck). The read path made zero LLM/Hindsight calls. A regression test now verifies cached brief recomputation uses only local SQLite and does not add memory calls.
- The one valid real-bank M6 generation then completed in 53.16 s (1,867 / 2,571 tokens), with `recall_ms=24,154`, `gather_ms=34,389`, `p3_ms=18,614`; no recall timeout was logged. It rendered 5 You owe, 6 They owe, 5 cited objections, 3 cited contact cards, and the pricing deck as the sole critical item. All 11 owed rows and all 5 objections had citations. The second and final Sandbox-R generation slot is spent on the misconfigured run; no more generations were made. `MEMORY_READ_ONLY=true` was verified on the process; no Hindsight write was attempted.
- Current checkpoint tokens: Sandbox-W P3 573/629; Sandbox-W pattern 216/40; misconfigured Sandbox-R P3 721/1,372; corrected real-bank Sandbox-R P3 1,867/2,571. Added 3,377 prompt / 4,612 completion to the earlier partially known totals, now 6,819 / 6,097. A3 backfill usage and earlier unlogged calls remain unknown.
- Screenshots saved (ignored): `artifacts/overhaul/checkpoint2-contacts-list.png`, `artifacts/overhaul/checkpoint2-contact-profile.png`. No real DB generation or write was performed. Sandbox-R's brief cache is in its copy only.
- Checkpoint 2 is **not green**: the Sandbox-W brief was empty, refresh produced no patterns, live correct was blocked by the retain cap, and no Brief screenshot was captured. Stop here for user direction; do not retry or exceed any call/retain cap.

### Follow-up Group 2 — pattern threshold (2026-09-30)

- `POST /api/contacts/{contact_id}/patterns/refresh` now requires three visible facts across at least two distinct meetings before making its single app LLM call. Below either threshold it returns cached patterns plus a stable `reason`, without calling the LLM or overwriting the cache. The OpenAPI client was regenerated offline from `app.openapi()`; the schema response is documented above.
- Contacts profile Refresh is always visible but disabled unless visible facts span two meetings, with the requested tooltip. A returned threshold reason or request error is shown inline.
- Tests first: same-meeting facts skip without LLM; two-meeting facts invoke FakeLLM once and retain valid citations. Frontend threshold tooltip regression added. Backend: 702 passed, 1 skipped, 6 deselected; Ruff and mypy passed. Frontend: lint and TypeScript passed; Vitest 55 passed.
- Sandbox-W was restarted using `scripts/sandbox_w.sh` (DB `app.sandbox.db`, bank `ae-overhaul-test`, read-only false). Karan Shah has six meetings but the five visible facts all cite `m2_finedge`; the one requested refresh returned `patterns: []`, reason `Needs facts from at least 2 meetings`, and made no LLM call. No fact payload was sent.

### Stage C ticket C0 — cached Brief page (2026-09-30)

- Frontend/read-time only; no LLM or Hindsight calls. The cached M6 page now prioritizes critical items before amber alerts, sorts owed rows critical/overdue/date, caps each list at three with a show-more control, formats dates for display, shows overdue age and Watch only for overdue rows, omits empty sections, and removes the separate Memory-used card/duplicate facts count.
- The header counter reads the cached `memory_used` object; internal AE/Arjun attendees and contact cards are excluded; contact-card meetings are limited to past meetings, newest first, max three. Feedback uses monochrome accessible icon controls in section headers. Prepared can be set and undone with the existing POST/DELETE endpoints. Heading uses the meeting title without “Brief for”.
- Added cached-brief regression coverage for memory counts, due dates/order/density, internal attendees, empty Alerts, past-only contact meetings, accessible icon feedback and prepared undo. Focused Brief tests passed (10); lint and TypeScript passed. Broader frontend checks are rerun at final checkpoint.

### Accepted Checkpoint 2 fixes — group 4: Today/Capture/Brief polish

- Nudges now identify critical overdue items from cached brief enrichment and render other overdue reminders amber. “No history yet” is based on whether the account has any completed meeting (not only an earlier-scheduled one); first-meeting brief detection uses the same rule. Meeting summaries now expose `overdue_followups` and `has_notes` for the UI.
- Today excludes Priya Nair and Arjun Menon from attendee lines, formats customer attendees as `Name (role)`, shows overdue/other-open chips consistently, routes “Log notes” to `/capture?meeting=<id>`, and uses the demo-date chip with the compact Today label. Capture honors that meeting query, otherwise defaults to the newest meeting without notes; its selector/upload fields are equal height and the disabled extraction hint is explicit. The Capture page uses a compact label/subtitle, and cached objections cap at three with “Show N more”.
- Updated schema docs and generated API declarations offline from `app.openapi()` (28 paths); no live LLM/Hindsight calls. Tests: backend 705 passed, 1 skipped, 6 deselected; Ruff/mypy passed. Frontend lint/typecheck passed; 60 Vitest tests passed; production build passed with the existing >500 kB bundle advisory.

### Accepted Checkpoint 2 fixes — contacts group (2026-09-30)

- Contact list defaults to confirmed customer-side contacts only; `include_unconfirmed=true` adds needs-review customer contacts but never account-less internal people. Added the “Show unconfirmed (N)” toggle/chip and a confirmation PATCH that updates name/role and clears `needs_review`. The schema doc and offline OpenAPI client were updated in this commit.
- Contact timeline headings use “title · Mon D, YYYY”; kind labels are sentence-case chips, and source chips link to meetings. Fact and follow-up rows now expose keyboard-operable `…` menus; follow-up actions include mark/reopen, edit date, and confirmed delete. Contact cards defensively exclude internal contacts.
- Live correction-only retain: Hindsight `/health` was healthy (`database=connected`) before the call; guarded Sandbox-W printed bank `ae-overhaul-test`, DB `app.sandbox.db`, read-only false. Corrected one fact through `POST /api/memories/{id}/correct`; its note job completed with no error, and the contact profile showed the original hidden. This was the one newly authorized Hindsight retain; no other live retain was made.
- Gates: backend 703 passed, 1 skipped, 6 deselected; Ruff and mypy passed. Frontend lint and typecheck passed; 58 Vitest tests passed; production build passed (existing large-chunk warning only).

### Checkpoint 2 accepted fixes — group 0: sandbox guard

- Added executable `scripts/sandbox_w.sh` and `scripts/sandbox_r.sh`. Each exports its sandbox SQLite URL, expected `DEMO_USER_ID`, and memory mode; resolves and prints the effective `DATABASE_URL`, `BANK_ID`, and `MEMORY_READ_ONLY`; refuses any unexpected values before launching. W binds only :8001 with `ae-overhaul-test` and writes enabled; R binds only :8002 with `ae-user-demo-thomas` and read-only enabled. `--check` performs the same guards without starting a server.
- Guard tests cover expected settings and refusal of the wrong DB, bank, or read/write mode. `bash -n` and all 8 `test_sandbox_scripts.py` tests passed; Ruff passed. From now on use these scripts for sandbox starts, not hand-written uvicorn commands.

### Checkpoint 2 accepted fixes — group 1: first-meeting brief

- Root cause: the empty-evidence P3 instructions contradicted themselves, and `_map_draft` then dropped every memory-mode item without a citation. With no evidence, that left the first-meeting brief empty and therefore intentionally uncached.
- P3 now has an explicit first-meeting instruction. Only first-meeting `agenda` and `your_questions` suggestions with empty evidence IDs may be uncited; claims and every other memory-mode item still require citations. A deterministic fallback guarantees a short agenda and 2–3 generic planning questions when P3 returns empty/partial output. The Attendees section is retained even when the meeting has no recorded attendees, and nonempty first-meeting output is persisted. The existing UI labels it “No history yet”.
- FakeLLM regression test forces an empty draft and verifies Attendees, 3 agenda items, 3 questions, no citations on suggestions, no Hindsight recalls, and a subsequent cache hit. Backend gates: 702 passed, 1 skipped, 6 deselected; Ruff and mypy passed.
- Sandbox-W live check initially showed Attendees empty because the scheduled attendee had no prior meeting citation. Narrowed the first-meeting exception to display current, account-side scheduled attendees without history citations; internal attendees remain excluded. The one allowed retry on `m_c2266acc` succeeded in 5.58 s with 641 prompt / 580 completion tokens (temperature fallback succeeded); cached brief `br_5c3700ca` has 1 attendee, 3 agenda items, 3 questions, zero memory use, and `first_meeting=true`. The earlier call on this meeting used 641 / 530 tokens and returned zero attendee rows; both first-meeting call slots are now spent.

### Stage C ticket C1 — Ask page

- Replaced the Ask placeholder with a scopeable Q&A page. The scope dialog is populated from account/contact/meeting list queries; switching scope clears the React-only thread. Each request sends only the last three turns. Suggested questions are static per scope (no P4 call). The selected answer's source rail links to meetings and displays meeting title/date plus quoted evidence; ungrounded answers show the fixed “Not found in memory” callout. Pin to brief is available for meeting-scoped grounded answers; Remember this is retained.
- Kept the existing Brief and Contact Ask panels, replacing generated suggestions with the same static scope prompts and avoiding raw meeting IDs in source labels. No new endpoint/schema and no LLM/Hindsight calls during implementation.
- Tests: Ask page scope selection, citations, static suggestions, and ungrounded callout; lint and TypeScript passed; Ask/Brief/Contacts focused Vitest tests passed (15).

### Stage C ticket C2 — Memory inspector

- Added `GET /api/memory/overview` with visible extracted-fact counts by kind, cumulative fact counts after each completed meeting per account, app-side hidden/corrected override rows, and the current SQLite-derived style profile. The Hindsight stats field uses the SDK's cached bank-stats GET (`refresh=false`) with a 2-second request/deadline timeout; failure returns `null` without failing SQLite data. No Hindsight writes or LLM calls.
- Added the Memory inspector with a memory on/off control that only GETs cached briefs, meeting selection, a dependency-free SVG growth line per account, SQLite fact-kind totals, nullable Hindsight bank counts, hidden items with Unhide, and style rules with a confirmation before Reset. No illustrative values are supplied.
- Updated `docs/data-model-and-schemas.md` and regenerated the frontend client offline from `app.openapi()` (29 paths). Backend focused checks: 17 passed across overview and memory-service timing tests; Ruff/mypy passed. Frontend Memory tests: 2 passed; lint and TypeScript passed.

### Stage C ticket C3 — accessibility and responsive polish

- Added explicit Ask scope loading/empty/error states and source selection per answer; source labels resolve to meeting title + date from local SQLite (never raw IDs), with selected citation quotes shown in the rail. Brief/Contact Ask inputs and source links have visible keyboard focus styling. Updated shell/Ask tests for compact page labels and static suggestions.
- Full backend gates: 708 passed, 1 skipped, 6 deselected; Ruff and mypy passed. Frontend: 65 Vitest tests passed, lint and TypeScript passed, production build passed (existing 594 kB main-chunk advisory).
- Responsive classes use single-column layouts below `lg` and compact wrapping at mobile widths. No browser/viewport automation is available in this environment, so actual 1280/1024/390 visual inspection remains a manual verification item; no screenshots are claimed for this ticket.

### Stage C follow-up — contact pattern card

- Hide “What I have learned” when no cached patterns exist. Move Refresh into “You stay in control” as a compact link-style button, disabled with the existing two-distinct-meeting hint until eligible. Tests cover both no-pattern/threshold and cached-pattern/eligible states; focused contact profile tests: 6 passed; full frontend gates rerun for C4.

### Stage C ticket C4 — verification / handover (complete)

- Sandbox-R guard check resolved `DATABASE_URL=sqlite:///./app.sandbox-r.db`, bank `ae-user-demo-thomas`, `MEMORY_READ_ONLY=true`; Hindsight health was healthy before calls. Three authorized Ask reflects completed sequentially (no brief generation, retain, or Hindsight write): (1) Anita budget, 13.81 s, grounded to `Budget and process · Jul 28, 2026`; about $40K and first-year cost including onboarding; (2) same-thread follow-up on the ROI one-pager, 13.06 s, grounded to the same meeting; include total first-year cost, visible assumptions, current-system comparison, and deadline; (3) Rahul favourite food, 11.32 s, fixed “Nothing in memory covers that yet.” with no citations. Reflect token counts were unavailable in the API response. Sandbox-W Karan refresh had zero cited patterns, so both conditional real-DB pattern refreshes were correctly skipped.
- Created and retained `/home/saisivakesh/meeting-prep-backups/app.db.post-overhaul`; it and `backend/app.db` pass `PRAGMA integrity_check`. Real-DB GETs on temporary port :8003 with Hindsight `MEMORY_READ_ONLY=true` returned cached `br_ae8ce076`: 47 facts from 5 meetings; 5 You owe, 6 They owe, 5 objections, 3 contact cards; only critical item is the cited pricing deck (25 days overdue). Meetings GET returned 17 rows; M6 is upcoming with history and 3 overdue follow-ups. Nudges GET marks only the pricing deck critical. No real-DB brief generation, app HTTP write, Hindsight write, or pattern refresh occurred.
- `contactpatterncache` is the expected B4 `ContactPatternCache` table: first API startup created it from the model metadata, as covered by the original startup-table authorization. It has zero rows. The backup predates that startup and is retained as requested; `backend/app.db` is left as-is. This is expected, not an incident.
- Recreated only `backend/app.sandbox.db` from `backend/app.db` using `sqlite3`'s `.backup` API. Integrity passed; it contains the 17 baseline meetings and none of the synthetic capture/test meetings. Sandbox-W was restarted only through `scripts/sandbox_w.sh` and its guard resolved DB `sqlite:///./app.sandbox.db`, bank `ae-overhaul-test`, `MEMORY_READ_ONLY=false`. Sandbox-R is stopped. Vite remains on :5174. The real API on :8000 was not started.
- C4 final gates before the last frontend-only contact-card adjustment: backend 709 passed, 1 skipped, 6 deselected; Ruff/mypy passed. Final frontend gates after the adjustment: 66 Vitest tests passed; lint, TypeScript and production build passed (594 kB chunk advisory). Contact profile focused tests: 6 passed. No browser screenshots were available; viewport inspection remains manual.

#### Click-by-click screen checklist (manual; screenshots not captured)

1. **Today:** [read-only GET] open Today; check demo-date chip, customer-only attendee line, prepared/brief status, overdue vs other-open chips; search meetings/contacts. Click “Log notes” (navigation only) and verify Capture preselects the meeting.
2. **Capture:** [read-only] select a meeting and inspect loading/empty/error states, disabled hint, equal-height meeting/upload controls. [LLM call] “Extract memories” runs P1/P2; [Hindsight write] Save to memory retains; avoid both for a read-only recording. A failed-save Retry reuses the draft but may call retain again after health is confirmed.
3. **Brief:** [read-only GET] open “Pilot decision”; verify title/account/date, customer-only attendees, sole critical pricing-deck alert, amber remaining overdue items, top-three owed lists/“Show N more”, localized dates, citations, 47 facts from 5 meetings. Memory toggle reads cached briefs. [SQLite write] toggle Prepared / undo; section feedback also writes. Ask drawer questions invoke Hindsight reflect and save the Ask answer in SQLite.
4. **Contacts list:** [read-only GET] search/filter; verify confirmed-only default and “Show unconfirmed (N)” / Unconfirmed chip; open a contact.
5. **Contact profile:** [read-only GET] check header and Timeline/Facts/Follow-ups/Preferences tabs, sentence-case kinds, date headings and source links; keyboard-open a row menu. [SQLite writes] follow-up mark-done/edit/delete and contact confirmation. [Hindsight/app override writes] correct/hide; Refresh invokes the app LLM only when facts span at least two meetings; Add note retains to Hindsight. Do not trigger writes for a read-only recording. Open Ask drawer (reflect is an LLM call).
6. **Ask page:** [read-only GET] change account/contact/meeting scope and inspect static suggestions. [Hindsight reflect + SQLite AskAnswer write] ask a grounded question, follow up, select the earlier answer and inspect citations; ask an uncovered question for the fixed not-found reply. [SQLite write] Pin to brief; [Hindsight retain] Remember this.
7. **Memory inspector:** [read-only GET] load overview and cached memory/no-memory briefs; inspect growth, fact-kind totals, hidden items and style rules. [SQLite writes] Unhide and confirmed Reset; “Open a brief” navigates to GET-backed brief view.
8. Repeat the visual/focus pass at 1280, 1024, and 390 widths; check tab order, visible focus, accessible names, wrapping and contrast. These viewport checks require a browser and remain unverified here.

#### Final implementation and handover

- Requested commit references: C0 Brief page fixes `4ac0226`; C1 Ask `f0cc234`; C2 Memory inspector `11a195a`; first-meeting brief fix `eb08833`; Contacts list/profile confirmation, internal-contact exclusion, sentence-case kinds, human dates, and per-item controls `a8d5452` (brief contact-card internal exclusion `4ac0226`, pattern threshold `97cf5cb`); A8 Today/Capture/Brief polish `7078cb3`. Final follow-ups: C3 `46dd72c`, critical nudge fallback `af7103c`, hide empty pattern card `9d4947d`, and this handover commit.
- Wireframe gap list: all listed product gaps are implemented (shell, Today search/scheduling/nudges/style card, meeting brief and cached memory toggle, contact list/profile/tabs/pattern controls, full Ask and drawer, capture review/save, Memory inspector). Explicitly not built by design: voice-note capture; illustrative 1/5/20 demo cards were replaced with real fact counts. Orange annotation pins/yellow legend are documentation, not UI. Browser screenshots and actual responsive viewport inspection remain unverified.
- LLM/token accounting: no LLM calls in this final user turn. Stage C C4 used 3 Hindsight Ask reflects (budget max 3), 0 brief generations, 0 pattern refreshes (condition not met), and 0 Hindsight writes. Their token counts are unavailable. Existing notes record partial app-provider totals of 8,101 prompt / 7,207 completion tokens; A3 backfill and earlier unlogged calls remain unknown, so a complete lifetime token total cannot be asserted. The logged subset includes 27 logical app calls (P1/P2/P3/pattern) in the pre-C4 tally; older per-call counts and temperature retries are itemized above. Original Sandbox-R misconfigured P3 (721/1,372) is historical and invalid gate evidence, but included in the partial tally.
- Known limitations: no browser automation/screenshots; manual 1280/1024/390 inspection pending; historical unlogged token usage cannot be recovered; Karan's sandbox pattern refresh had no cited pattern; Hindsight SDK cannot delete an individual memory, so hide/correct only suppress within this app; the production JS bundle remains above the 500 kB advisory threshold.
- Recording commands (not run): stop sandbox APIs with `kill -TERM "$(lsof -tiTCP:8001 -sTCP:LISTEN)"` and Vite :5174 with `kill -TERM "$(lsof -tiTCP:5174 -sTCP:LISTEN)"`. Start the real API from `backend/` with `uv run uvicorn app.main:app --host 127.0.0.1 --port 8000`; start real Vite from `frontend/` with `npm run dev -- --host 127.0.0.1 --port 5173`. Do not start both API configurations concurrently against the same DB.
- Pre-push checks (read-only): see final handover response for branch/status, ahead count, secret scan, tracked-file audit, and distinct author/committer emails. No push was performed.
- Pre-push snapshot: branch `main`, 50 commits ahead of `origin/main`; the only worktree change is the pre-existing `.gitignore` addition `deliverables/`. No `.env`, database, `seed.log`, `artifacts/`, or `deliverables/` files are tracked. Distinct author/committer email: `saisivakesh1708@gmail.com`.
- Neither `gitleaks` nor `trufflehog` is installed. Fallback grep over added lines reported potential pattern matches (values withheld) in these file/commit pairs only: `backend/app/llm/providers/base.py` — `3f667b1`; `backend/tests/unit/test_ask_service.py` — `27c69a0`; `docs/ui-overhaul-notes.md` — `ca5f7f8`, `183d545`. These correspond to token-usage identifiers/documentation and synthetic test data; no credential value was confirmed. No AKIA, gsk, Anthropic-key-specific, or private-key-header match occurred.
