# Meeting Prep Agent

A meeting prep agent for a B2B sales rep. After each meeting it ingests the
transcript into [Hindsight](https://github.com/vectorize-io/hindsight) memory;
before the next meeting it produces a one-screen brief where every
claim cites a past meeting. Memory is the product: the demo compares the brief
with and without memory.

## Stack

- **Backend:** Python 3.11+, FastAPI, Pydantic v2, SQLModel on SQLite, `uv`
- **Memory:** self-hosted Hindsight (Docker) via `hindsight-client`
- **LLM:** switchable between `openai`, `groq` and `anthropic` in `.env`, set
  separately for the app and for Hindsight
- **Frontend:** React + Vite + TypeScript, Tailwind, shadcn/ui, TanStack Query
- **Tests:** pytest (with httpx), Vitest

## Status

Built:

- Transcript ingest: `POST /api/meetings/{id}/notes` returns a job id and runs in the
  background; extraction feeds a commitments ledger in which every commitment needs a
  quote found verbatim in the transcript, and overdue is computed, never stored
- Hindsight memory: the raw transcript is retained per meeting through the
  `memory_service` gateway, with a live contract test
- Cited briefs: every item in a memory brief cites a past meeting, with a
  With memory / Without / Side by side toggle
- Contact timeline of what memory holds about a person
- Rule-based style learning from brief feedback, applied when a brief is read
- Ask panel: scoped questions answered from memory, with a fixed reply when memory has
  nothing
- Snapshot tooling for the local database and cached briefs
- Switchable LLM providers (OpenAI, Groq, Anthropic), set separately for the app and
  for Hindsight

Not built: golden end-to-end tests, the stakeholder map, nudges, and the cross-deal
pattern item in briefs.

Briefs are pre-generated and cached. Opening a brief is a plain GET and never
generates one; generating takes about a minute and is a deliberate POST.

## Quick start

```bash
cp .env.example .env         # then fill in the values below
docker compose up -d hindsight   # Hindsight on :8888 (API) and :9999 (UI)
cd backend && uv run uvicorn app.main:app --port 8000
cd frontend && npm install && npm run dev   # http://localhost:5173, proxies /api to :8000
```

In `.env`, choose the LLM provider by setting `LLM_PROVIDER` (`openai`, `groq` or
`anthropic`), `LLM_MODEL`, and the matching `*_API_KEY`. Hindsight has its own
`HINDSIGHT_LLM_PROVIDER`, `HINDSIGHT_LLM_MODEL` and `HINDSIGHT_LLM_API_KEY`; its
model must support tool calling. Startup fails with a message naming the variable
if the provider is unknown or a key is missing. `.env` is gitignored; never commit it.

```bash
cd backend && uv run pytest              # unit tests (fakes, no network)
cd backend && uv run pytest -m live      # Hindsight contract test (needs the container and a key)
cd backend && uv run pytest -m live_llm  # LLM smoke test per provider (skipped without that key)
cd backend && uv run ruff check . && uv run mypy app
cd frontend && npm run lint && npx tsc --noEmit -p tsconfig.app.json && npm test
```

## Documentation

Design and specifications are in [`docs/`](docs/): the feature spec, technical
design, data model and schemas, Hindsight integration, prompt specs, synthetic
data spec, acceptance criteria and the task breakdown. Contributor and coding
agent rules are in [`AGENTS.md`](AGENTS.md).

## License

MIT, see [LICENSE](LICENSE).
