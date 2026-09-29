# AGENTS.md — Meeting Prep Agent

Rules for every AI coding agent working in this repo. Read this file first, every session.

## What we are building

A meeting prep agent for a B2B sales rep. After each meeting it ingests the transcript into
Hindsight memory; before the next meeting it produces a one-screen brief where every claim
cites a past meeting. Memory is the product: the demo compares the brief with and without memory.

## Source-of-truth docs (in `docs/`)

| Doc | Use it for |
| --- | --- |
| `feature-spec.md` | What each feature does (F1–F23) |
| `technical-design.md` | Stack, architecture, modules, API routes, flows |
| `data-model-and-schemas.md` | Every Pydantic / SQLModel class, enums, tags. **Wins on any conflict** |
| `hindsight-integration.md` | `memory_service` interface, call recipes, failure handling |
| `prompt-specs.md` | Every prompt (P1–P4, R1–R5, G1) and its fixture test |
| `synthetic-data-spec.md` | Accounts, contacts, meetings, story beats B1–B6 |
| `acceptance-criteria.md` | Definition of done, acceptance per feature, golden scenarios |
| `task-breakdown.md` | Tickets T01–T31, dependencies, lanes |

If code and a doc disagree, stop and report it. Do not "fix" the doc to match your code.

## Stack (do not change)

- Backend: Python 3.11+, FastAPI, Pydantic v2, SQLModel on SQLite, `uv`
- Memory: self-hosted Hindsight (Docker) via `hindsight-client`
- LLM: switchable via `.env` between `openai`, `groq` and `anthropic`, set separately for the app
  (`LLM_PROVIDER`, `LLM_MODEL`) and for Hindsight (`HINDSIGHT_LLM_PROVIDER`, `HINDSIGHT_LLM_MODEL`).
  App calls go only through `backend/app/llm/client.py`; provider adapters live in `backend/app/llm/providers/`
- Frontend: React + Vite + TypeScript, Tailwind, shadcn/ui, TanStack Query
- Tests: pytest (+ httpx AsyncClient), Vitest

## Commands

```bash
docker compose up                      # hindsight :8888/:9999, api :8000, web :5173
cd backend && uv run pytest            # unit tests (fakes, no network)
cd backend && uv run pytest -m live    # Hindsight contract test
cd backend && uv run pytest -m live_llm  # LLM smoke test per provider (skipped without that key)
cd backend && uv run pytest -m golden  # golden scenarios G-1..G-4 (real Hindsight + configured LLM providers)
cd backend && uv run ruff check . && uv run mypy app
cd frontend && npm run lint && npx tsc --noEmit -p tsconfig.app.json && npm test
cd frontend && npm run gen:api         # regenerate API client from /openapi.json
make reset-demo                        # wipe SQLite + demo bank, reseed
```

## Hard rules

1. **Gateways only.** Only `app/memory/memory_service.py` imports `hindsight_client`.
   Only `app/db/repository.py` touches DB sessions. Only `app/llm/client.py` (and its adapters in `app/llm/providers/`) calls an LLM provider;
   provider SDKs (openai, groq, anthropic) are imported only inside `app/llm/providers/`.
2. **Tags via `app/memory/tags.py`.** Never type a tag string by hand.
3. **Hindsight signatures from the docs, never guessed.** Use the `hindsight-docs` skill
   (`npx skills add vectorize-io/hindsight-skills --skill hindsight-docs`) or the official docs.
4. **No uncited brief items.** In `memory` mode, items without citations are dropped in code.
5. **Never mock memory in the demo path.** Fakes (`tests/fakes/`) are for tests only.
6. **Time comes from `settings.demo_today`**, never `date.today()` / `datetime.now()` for business logic.
7. **Money is integer USD.** IDs follow the prefixes in the schemas doc.
8. **Prompts live in `app/llm/prompts/*.md`.** A prompt and its output model change together,
   and the prompt's fixture test is rerun.
9. **Schema changes** update the schemas doc, the model, and the generated frontend client in the same PR.
10. **No new dependencies** without saying why in the PR description.
11. **Secrets** only from the root `.env` (gitignored); never commit, print or log keys. `.env.example` lists every
    variable, including one key per provider. Never change `LLM_PROVIDER` / `HINDSIGHT_LLM_PROVIDER` in `.env`
    yourself; switching providers is the user's decision.
12. **Never regenerate seed transcripts at demo time.** `m6_finedge_live.txt` is hand-edited; do not overwrite it.
13. **Provider-neutral code.** Nothing outside `app/llm/` may depend on which provider is selected. Hindsight's
    model must support tool calling, whatever the provider.

## Working a ticket

1. Take one ticket from `task-breakdown.md` whose dependencies are merged.
2. Post a 5-bullet plan before coding.
3. Write tests for the ticket's acceptance criteria first.
4. Stay inside the ticket's listed files. If another module's interface must change, stop and explain.
5. Finish only when the Definition of done in `acceptance-criteria.md` is met.
6. Report: what changed, test output, anything not done, docs needing updates.

One ticket = one branch = one PR. Branch name: `t{NN}-{short-slug}`.

## Code style

- Python: type hints everywhere, `ruff` defaults, async for I/O, small functions, no bare `except`.
- Errors: raise typed errors from `app/core/errors.py`; the handler maps them to
  `{"error": {"code", "message"}}` with the codes in the schemas doc.
- Frontend: function components, hooks, TanStack Query for server state, no browser storage,
  Tailwind classes only; red = overdue/critical, amber = warning.
- Logging: structured, one line per external call with duration; never log transcripts in full.

## When unsure

Ask in the PR or stop and report. A clear question beats a confident guess, especially for
anything touching memory, citations, or the demo fixture.
