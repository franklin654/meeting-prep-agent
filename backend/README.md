# Meeting Prep Agent — Backend

FastAPI backend for the Meeting Prep Agent. See the repo root `AGENTS.md` and `docs/` for
architecture, schemas and rules.

## Commands

```bash
uv sync
uv run uvicorn app.main:app --reload
uv run pytest
uv run ruff check .
uv run mypy app
```
