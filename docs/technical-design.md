# Meeting Prep Agent — Technical Design

Sep 28, 2026 · @Thomas

Companion to the [Feature & Requirements Spec](https://claude.ai/code/artifact/a88c5f23-38e8-43fe-a34f-7c4a0b485693). This doc is written for AI coding agents: where it states a choice, agents follow it rather than pick their own.

## Stack decisions

Python FastAPI backend, self-hosted Hindsight in Docker for memory, SQLite for structured records, and a React + Vite frontend, all started with one `docker compose up`.

| Layer | Choice | Why |
| --- | --- | --- |
| Backend | FastAPI (Python 3.11+) | Async, Pydantic models double as LLM output schemas, auto OpenAPI docs agents can read. Chosen over Flask for typed validation out of the box |
| Package manager | uv | Fast installs, one lockfile, simple commands for agents |
| Memory | Hindsight, self-hosted Docker image `ghcr.io/vectorize-io/hindsight` + `hindsight-client` Python SDK | Hackathon requirement; retain / recall / reflect, tags, mental models, reflect citations |
| Structured store | SQLite via SQLModel | Contacts, accounts, meetings, commitments ledger, feedback. Zero setup; deterministic queries for overdue detection and UI lists |
| LLM | Switchable between `openai`, `groq` and `anthropic` via `.env`, set separately for the app and for Hindsight; model set by env var | One interface, no vendor lock-in; pick whichever provider has quota headroom. Free-tier rate limits apply (see Config) |
| Frontend | React + Vite + TypeScript, Tailwind CSS, shadcn/ui, TanStack Query | Polished UI fast; AI agents are highly fluent in this stack |
| Background work | FastAPI `BackgroundTasks` | Retain and reflect can take seconds; no Celery or Redis needed at hackathon scale |
| Tests | pytest + httpx `AsyncClient`; Vitest for a few UI units | Golden-scenario tests are the agents' definition of done |
| Run | Docker Compose: `hindsight`, `api`, `web` | One command for the team and for judges |

## Architecture

The web app talks only to the FastAPI backend; inside it, the services share two gateway modules, one for Hindsight and one for SQLite.

&#91;embedded content: system architecture · web, API modules, stores\]

Services never import the Hindsight SDK or SQLModel sessions directly. Keeping all memory calls behind one module lets agents change memory behaviour in one place and lets tests swap in a fake memory service.

## Repo structure

One monorepo with `backend/`, `frontend/`, `data/` and `docs/`; agents create files only where this layout says.

```text
meeting-prep-agent/
├─ AGENTS.md                 # rules for coding agents (see Testing)
├─ docker-compose.yml
├─ .env.example
├─ docs/                     # exported specs, schemas, prompts
├─ data/
│  ├─ seed/                  # synthetic accounts, contacts, transcripts (JSON)
│  └─ scripts/seed.py        # loads seed data through the real ingest API
├─ backend/
│  ├─ pyproject.toml
│  ├─ app/
│  │  ├─ main.py              # FastAPI app, router registration
│  │  ├─ config.py            # pydantic-settings, reads .env
│  │  ├─ api/                 # routers: meetings, briefs, contacts, feedback, memory
│  │  ├─ schemas/             # Pydantic models: extraction, brief, API I/O
│  │  ├─ services/            # ingest.py, brief.py, reasoning.py, preferences.py
│  │  ├─ memory/              # memory_service.py (only Hindsight caller), tags.py
│  │  ├─ db/                  # models.py (SQLModel), repository.py, session.py
│  │  ├─ llm/                 # client.py, providers/ (openai, groq, anthropic adapters), prompts/*.md
│  │  └─ core/                # errors, logging, time utils
│  └─ tests/
│     ├─ unit/
│     ├─ golden/              # seeded end-to-end scenarios
│     └─ fakes/               # FakeMemoryService, FakeLLM
└─ frontend/
   ├─ package.json
   └─ src/
      ├─ pages/               # Dashboard, Brief, ContactTimeline
      ├─ components/          # BriefSection, CitationChip, MemoryToggle...
      ├─ api/                 # typed client generated from OpenAPI
      └─ lib/
```

## Backend modules

Each module has one job and a narrow interface; routers stay thin and call services only.

| Module | Responsibility | Depends on |
| --- | --- | --- |
| `api/*` | HTTP routing, request validation, status codes. No business logic | services |
| `services/ingest.py` | Save meeting, run structured extraction, write commitments to ledger, retain transcript to Hindsight, trigger reasoning job | llm, memory, db |
| `services/brief.py` | Build a brief for a meeting: gather attendees, recall/reflect per section, merge ledger data, apply style preferences, attach citations, include pinned Ask answers | memory, db, llm |
| `services/ask.py` | Answer a scoped question with reflect, enforce citations, store the answer for pinning, retain explicit "Remember this" notes | memory, db |
| `services/reasoning.py` | Contradiction detection, cross-contact gaps, cross-deal patterns, daily nudges | memory, db |
| `services/preferences.py` | Turn feedback events into preference memories; return current style profile | memory, db |
| `memory/memory_service.py` | Wrapper over `hindsight-client`: bank setup, `retain_meeting`, `retain_note`, `recall`, `reflect`, mental model helpers, tag building. Only file that imports the SDK | Hindsight |
| `memory/tags.py` | Tag conventions as functions (`account_tag(id)`, `contact_tag(id)`…) so nobody hand-types tag strings | — |
| `db/repository.py` | All SQLite reads and writes | SQLModel |
| `llm/client.py` | `complete_json(prompt, schema)` for structured calls and `complete_text(prompt) -> str` for plain text; retries and timeouts | `llm/providers/` |
| `llm/providers/` | One adapter per provider (`openai`, `groq`, `anthropic`) behind the client; the only place provider SDKs are imported | provider SDKs |

A "no memory" mode flag on `brief.py` skips all memory calls. It powers the with vs without toggle and must use the same prompt so the comparison is fair.

## Data storage

Hindsight holds what the agent remembers and reasons over; SQLite holds the records the UI lists and the rules that must be exact, like overdue dates.

### Hindsight usage rules

- **One bank per user** (`bank_id = "ae-<user_id>"`; the demo has one AE). The docs recommend per-user banks for the simplest setup and strongest isolation. [source](https://hindsight.vectorize.io/faq)
- **Retain the whole transcript as one document**, with `id = "meeting-<id>"`. The docs advise passing full conversations and not pre-extracting facts; re-retaining the same id replaces the old document, which gives idempotent ingestion for free. [source](https://hindsight.vectorize.io/faq)
- **Timestamped, speaker-prefixed lines** in transcripts (`[2026-08-12T10:32Z] Rahul (VP Eng): …`). The docs say this improves attribution and timing. [source](https://hindsight.vectorize.io/faq)
- **Tags on every retain:** `account:<id>`, `contact:<id>` per attendee, `meeting:<id>`; preference memories get `kind:preference`. Tags filter recall and reflect. [source](https://hindsight.vectorize.io/faq)
- **Metadata:** `meeting_date`, `title`, `source`. Metadata is returned with each recalled memory, which is how citations link back to a meeting; it is not a filter. [source](https://hindsight.vectorize.io/faq)
- **Entity labels** with `tag: true` for a `fact_kind` vocabulary (`commitment`, `objection`, `personal`, `deal_fact`, `competitor`), so each brief section can recall only its kind. Verify the bank config shape in the Entity Labels docs before coding.
- **Recall vs reflect:** recall (fast, raw facts) for lists like touchpoints and watch-outs; reflect for synthesis sections and contradiction checks, using `response_schema` for structured output and its returned citations. [source](https://hindsight.vectorize.io/faq)
- **Mental models:** one per account ("What is the current state of our relationship with \<account>?") and one per user ("How does this user like their briefs?"). They are standing answers kept current in the background, so the brief reads them instantly. [source](https://hindsight.vectorize.io/faq)

### SQLite tables

| Table | Key columns |
| --- | --- |
| `accounts` | id, name, industry, deal\_value, stage |
| `contacts` | id, account\_id, name, aliases (JSON), role |
| `meetings` | id, account\_id, title, scheduled\_at, status (`upcoming` / `done`), transcript, ingested\_at |
| `meeting_attendees` | meeting\_id, contact\_id |
| `commitments` | id, meeting\_id, owner (`us` / `them`), contact\_id, text, due\_date (nullable), status (`open` / `done`), source\_quote |
| `briefs` | id, meeting\_id, mode (`memory` / `no_memory`), content (JSON), created\_at |
| `feedback` | id, brief\_id, section, action (`up` / `down` / `more` / `less` / `collapsed`), created\_at |
| `ask_answers` | id, scope\_type (`account` / `contact` / `meeting`), scope\_id, question, answer (JSON with citations), pinned\_to\_meeting\_id (nullable), created\_at |

Commitments live in both places on purpose: Hindsight remembers them in context, the ledger answers "what is overdue today" exactly.

## API endpoints

All routes live under `/api`, return JSON, and are documented automatically at `/docs`; the frontend client is generated from that OpenAPI spec.

| Method + path | Purpose | Returns |
| --- | --- | --- |
| `GET /api/meetings?status=upcoming` | Dashboard list | meetings with attendees and brief status |
| `POST /api/meetings/{id}/notes` | Submit transcript or notes after a meeting | `202` + ingest job id |
| `GET /api/jobs/{id}` | Poll ingest or reasoning job | `pending` / `done` / `failed` + summary of learned facts |
| `POST /api/meetings/{id}/brief?mode=memory\|no_memory` | Generate a brief | brief JSON with sections and citations |
| `GET /api/meetings/{id}/brief` | Latest stored brief | brief JSON |
| `POST /api/ask` | Scoped question: `{question, scope_type, scope_id, history?}` | answer, citations, `ask_answer_id` |
| `POST /api/ask/{id}/pin` | Pin an answer to a meeting's brief: `{meeting_id}` | updated brief JSON |
| `POST /api/memories/notes` | "Remember this": `{text, scope_type, scope_id}` | `202` + job id |
| `GET /api/contacts/{id}/timeline` | Memory inspector for a contact | dated memories with source meeting |
| `GET /api/accounts/{id}/stakeholders` | Stakeholder map (P1) | contacts with role, stance, last contact |
| `POST /api/briefs/{id}/feedback` | Section feedback | updated style profile |
| `GET /api/nudges` | Daily digest (P1) | overdue commitments, silent contacts, ready briefs |
| `GET /api/health` | Liveness, checks Hindsight and DB | status per dependency |

Errors use one shape: `{"error": {"code": "...", "message": "..."}}`. Hindsight being down returns `503` with code `memory_unavailable`, never a stack trace.

## Key flows

Four flows carry the whole product; each is a straight sequence, so agents implement them as ordered steps in one service function.

### Ingest (after a meeting)

1. `POST /notes` saves the transcript on the meeting row and returns `202`.
2. Background task: `llm.complete_json` with the extraction schema → contacts, commitments, objections, deal facts.
3. Entity resolution against `contacts` (name + aliases + account); unknown people are created and flagged.
4. Open commitments for this account that the transcript acknowledges as delivered are marked done; new commitments are written to the ledger with `source_quote`.
5. `memory.retain_meeting` sends the timestamped transcript with tags and metadata.
6. `reasoning.check_changes(account)` runs reflect for contradictions and stores alerts.
7. Job marked `done` with a "learned" summary the UI shows as a toast.

### Brief (before a meeting)

1. Load meeting, attendees, account from SQLite.
2. In parallel (`asyncio.gather`): read the account mental model; recall per section with `fact_kind` and contact tags; reflect for unresolved objections; query ledger for open and overdue commitments; load the style profile.
3. One LLM call assembles the brief JSON from those inputs only, with every item carrying a `citations` list.
4. Drop any item with no citation, apply style (section order, length, hidden sections), store and return.

### Feedback

1. `POST /feedback` stores the event.
2. `preferences` retains a short sentence ("User collapsed personal touchpoints on 2026-10-02") tagged `kind:preference`.
3. The user mental model refreshes; the next brief reads the updated style.

### Ask (P1)

1. `POST /api/ask` receives the question, the scope (account, contact or meeting) and up to the last 3 Q&A pairs from the panel.
2. `tags.py` builds the tag filter from the scope; a meeting scope expands to its account and attendee tags.
3. `memory.reflect` runs with those tags, the prior Q&A as extra context, and a `response_schema` of `{answer, citations[]}`.
4. If reflect returns no citations, the answer is replaced with "Nothing in memory covers that yet", never a guess.
5. The answer is stored in `ask_answers` and returned; the question itself is not retained to Hindsight.
6. Pin: `POST /api/ask/{id}/pin` links the answer to a meeting; `brief.py` renders pinned answers as a "Your questions" section.
7. Remember this: `POST /api/memories/notes` retains the user's note with scope tags plus `kind:note`, as a background job.

## LLM usage

The app makes two kinds of LLM calls, extraction and brief assembly, both returning JSON validated against Pydantic models; everything else goes through Hindsight.

- **Providers:** `llm/client.py` delegates to one adapter per provider in `llm/providers/`, chosen by `LLM_PROVIDER`; nothing outside `app/llm/` depends on the choice. Structured output per provider: `openai` uses structured outputs / JSON mode with the Pydantic JSON schema; `groq` uses its OpenAI-compatible API with JSON mode; `anthropic` uses a forced tool call whose `input_schema` is the Pydantic JSON schema. The result is always re-validated with Pydantic.
- **Structured only:** Every app call uses `complete_json(prompt, PydanticModel)`. Invalid JSON gets one retry with the validation error appended, then the job fails loudly.
- **Prompts as files:** Prompts live in `backend/app/llm/prompts/*.md` with `{placeholders}`, never inline strings, so the prompt spec doc maps one-to-one to files.
- **Grounding rule:** The brief prompt receives only recalled memories, reflect output and ledger rows, each with an id. The model must cite those ids; uncited items are dropped in code, not trusted to the prompt.
- **Temperature:** 0 for extraction; low (about 0.3) for brief wording.
- **Timeouts:** 30 s per call, surfaced as `llm_timeout` errors.
- **Cost guard:** Briefs are cached per meeting and mode; regenerate only on new notes or explicit refresh.

## Frontend

Three pages, one shared layout, server state in TanStack Query and nothing in browser storage.

| Page | Route | Key components |
| --- | --- | --- |
| Dashboard | `/` | UpcomingMeetingList, NudgeDigest, LogNotesDialog |
| Brief | `/meetings/:id` | MemoryToggle (side-by-side with / without), BriefSection, CitationChip, AlertBadge, FeedbackControls, PersonalizationMeter, AskPanel (meeting scope) |
| Contact timeline | `/contacts/:id` | MemoryTimeline, FactCard (fact, date learned, source meeting), StakeholderMap (P1), AskPanel (contact scope) |

**AskPanel:** A collapsible right-side drawer with a question box, 3 suggested questions generated from the brief (e.g. "What did Anita say about Q4 budget?"), answers with CitationChips, and "Pin to brief" and "Remember this" buttons. Panel history lives in React state only and resets on page change.

- **Styling:** Tailwind + shadcn/ui; red for overdue, amber for watch-outs, neutral otherwise.
- **API client:** Generated from `/openapi.json` (e.g. `openapi-typescript`), so types never drift from the backend.
- **Feedback UX:** Collapse, thumbs and more/less controls on every brief section; a toast shows what was learned.
- **States:** Skeleton loaders while a brief generates; an explicit empty state for first-time contacts.

## Config, local dev and deployment

The demo runs locally only, with Docker Compose; the service will not be hosted.

- **Services:** `hindsight` (ports 8888 API, 9999 UI, data volume), `api` (FastAPI on 8000), `web` (Vite on 5173, proxies `/api`).
- **Stable worker id:** Set `HINDSIGHT_API_WORKER_ID` to a fixed value in compose. The docs warn that Docker's rotating hostname otherwise leaves background jobs stuck after a restart. [source](https://hindsight.vectorize.io/faq)
- **Machine:** Self-hosted Hindsight needs at least 4 GB RAM. [source](https://hindsight.vectorize.io/faq)
- **Env vars (`.env.example`):** `LLM_PROVIDER` (`openai` | `groq` | `anthropic`), `LLM_MODEL`, one key per provider (`OPENAI_API_KEY`, `GROQ_API_KEY`, `ANTHROPIC_API_KEY`), `HINDSIGHT_URL`, `HINDSIGHT_LLM_PROVIDER`, `HINDSIGHT_LLM_MODEL`, `HINDSIGHT_LLM_API_KEY` (mapped in compose onto Hindsight's `HINDSIGHT_API_LLM_*`), `HINDSIGHT_API_LLM_GROQ_SERVICE_TIER=on_demand` (only applies when Hindsight uses groq), `DATABASE_URL=sqlite:///./app.db`, `DEMO_USER_ID`.
- **Commands:** `docker compose up` → `uv run python data/scripts/seed.py` → open `localhost:5173`.
- **Reset:** `make reset-demo` wipes the SQLite file and Hindsight bank, then reseeds, so every rehearsal starts identical.
- **Fallback:** Hindsight Cloud is a managed option if local Docker is a problem on demo day; only `HINDSIGHT_URL` and a key change. [source](https://hindsight.vectorize.io/faq)

**LLM rate limits:** Retain and reflect make several LLM calls each, so a provider's free tier can throttle bulk seeding. Groq's free tier (8,000 tokens/minute) could not finish one retain+reflect cycle, so choose Hindsight's provider for headroom first. The seed script retains meetings one at a time with a pause and retry on `429`, and seeding runs once before rehearsals rather than on every reset.

## Testing and quality gates

Because agents write all code, a task is done only when its tests pass and the gates below are green; an agent's own claim of success does not count.

- **Unit tests:** Services tested with `FakeMemoryService` and `FakeLLM` from `tests/fakes/`, no network.
- **Golden scenarios:** `tests/golden/` seeds the FinEdge story against real Hindsight and asserts the brief flags the overdue pricing deck, the budget change, the personal touchpoint and the unanswered security objection. Run before every merge to `main`.
- **Contract tests:** Every LLM output parsed into its Pydantic model; every brief item and Ask answer has at least one citation, or the Ask answer is the explicit "nothing in memory" reply.
- **Lint and types:** `ruff` + `mypy` for backend, `eslint` + `tsc --noEmit` for frontend; CI fails on errors.
- **CI:** GitHub Actions runs lint, types, unit tests on each PR; golden tests run on `main` with secrets.

### AGENTS.md rules

- [ ] Read this doc and the feature spec before starting a task
- [ ] Only `memory/memory_service.py` imports `hindsight_client`
- [ ] Only `db/repository.py` touches the database session
- [ ] Never mock memory in the demo path; fakes are for tests only
- [ ] Schema or endpoint changes update the docs in the same PR
- [ ] Hindsight calls follow the official docs or the `hindsight-docs` agent skill, never guessed signatures
- [ ] One task per PR, with its tests

## Decisions log

Settled choices; agents do not reopen these witHindsight, self-hosted Docker image ghcr.iohout a team decision recorded here.

| # | Decision | Reason |
| --- | --- | --- |
| D1 | FastAPI over Flask | Pydantic validation and OpenAPI generation match schema-driven, agent-written code |
| D2 | Self-hosted Hindsight, Cloud as fallback | Full control for demo; quick switch if Docker fails |
| D3 | SQLite ledger alongside Hindsight | Exact overdue logic and UI lists; memory stays the reasoning layer |
| D4 | Retain raw transcripts, not our extracted facts | Follows Hindsight guidance; our extraction feeds the ledger only |
| D5 | One bank per user, tags for account and contact | Isolation plus scoped recall |
| D6 | Uncited brief items dropped in code | Enforces the no-hallucination requirement |
| D7 | React + Vite, not Next.js or Streamlit | Polished UI without SSR complexity |
| D8 | LLM provider switchable via `.env` (openai, groq, anthropic), replacing Groq-only | Groq's free tier (8,000 tokens/minute) could not finish one retain+reflect cycle; switching providers needs only env changes because all app calls go through one client with per-provider adapters |
| D9 | Local demo only, no hosting | Keeps effort on the product; judges see a live local demo |
| D10 | `fact_kind` entity labels with `tag: true` | Deterministic section-scoped recall (commitments, objections, personal, deal facts, competitors) |

## Open questions

None right now. The earlier questions on LLM provider, entity labels and hosting were settled as D8–D10.

## Sources

- [Hindsight FAQ](https://hindsight.vectorize.io/faq) (docs version 0.10)
- [Hindsight agent skills](https://github.com/vectorize-io/hindsight-skills) (install `hindsight-docs` for coding agents)
