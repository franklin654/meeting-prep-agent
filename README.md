# Meeting Prep Agent

A meeting prep agent for a B2B sales rep. After each meeting it ingests the
transcript into [Hindsight](https://github.com/vectorize-io/hindsight) memory;
before the next meeting it is meant to produce a one-screen brief where every
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

Done:

- Foundation: project scaffold, schemas, config validation, Docker Compose
- Data layer: SQLModel tables and repository, synthetic seed data, a transcript
  generator and validator, and 15 seed transcripts plus the live-demo transcript
- Memory layer: the `memory_service` gateway around Hindsight, with a live
  contract test
- LLM client with OpenAI, Groq and Anthropic adapters

Still to come: the ingest service, the brief service and the UI. Nothing in this
repository yet produces a brief.

## Quick start

```bash
cp .env.example .env         # then fill in the values below
docker compose up            # hindsight :8888/:9999, api :8000, web :5173
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
cd frontend && npm run lint && npx tsc --noEmit && npm test
```

## Documentation

Design and specifications are in [`docs/`](docs/): the feature spec, technical
design, data model and schemas, Hindsight integration, prompt specs, synthetic
data spec, acceptance criteria and the task breakdown. Contributor and coding
agent rules are in [`AGENTS.md`](AGENTS.md).

## License

MIT, see [LICENSE](LICENSE).
