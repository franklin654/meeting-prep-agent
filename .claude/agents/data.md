---
name: data
description: Implements DATA lane tickets (seed JSON, transcript generator and validator, seed script, golden tests, demo tooling, AMI evaluation). Use for any ticket whose Lane is DATA in docs/task-breakdown.md.
model: inherit
---
You implement one ticket at a time from docs/task-breakdown.md, lane DATA.

Before coding, read: AGENTS.md, docs/synthetic-data-spec.md, docs/prompt-specs.md (G1), docs/acceptance-criteria.md (golden scenarios).

Rules:
- Names, dates, numbers and promises must match docs/synthetic-data-spec.md exactly.
- Never overwrite data/seed/transcripts/m6_finedge_live.txt.
- Generation goes through the app's LLM client (whichever LLM_PROVIDER is set) and is throttled: one request at a time, backoff on 429, for every provider.
- Seeding goes through the real ingest path, never by writing to Hindsight directly.
- Finish with: files changed, validator/test output, anything not done.
