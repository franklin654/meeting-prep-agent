# Meeting Prep Agent — Hindsight Integration Spec

Sep 28, 2026 · @Thomas

Companion to the [Data Model & Schemas](https://claude.ai/code/artifact/2a411140-fa53-434d-b52d-2261eba4b678), which defines the tags, bank config and payloads this doc wires up. Checked against the Hindsight docs, version 0.10.

## Setup

Hindsight runs as one Docker service; its LLM provider (`openai`, `groq` or `anthropic`) and model are set in `.env` via `HINDSIGHT_LLM_PROVIDER`, `HINDSIGHT_LLM_MODEL` and `HINDSIGHT_LLM_API_KEY`, independently of the app's provider; the backend talks to it only through `hindsight-client`, and coding agents install the official `hindsight-docs` skill so they read real signatures instead of guessing.

```yaml
# docker-compose.yml (excerpt)
hindsight:
  image: ghcr.io/vectorize-io/hindsight:latest   # pin a version tag once chosen
  ports: ["8888:8888", "9999:9999"]              # API, UI
  environment:
    HINDSIGHT_API_LLM_PROVIDER: ${HINDSIGHT_LLM_PROVIDER}   # openai | groq | anthropic
    HINDSIGHT_API_LLM_MODEL: ${HINDSIGHT_LLM_MODEL}
    HINDSIGHT_API_LLM_API_KEY: ${HINDSIGHT_LLM_API_KEY}
    HINDSIGHT_API_LLM_GROQ_SERVICE_TIER: on_demand         # only applies when the provider is groq
    HINDSIGHT_API_WORKER_ID: hindsight-demo-1    # stable, prevents stuck jobs
  volumes: ["hindsight-data:/home/hindsight/.pg0"]
```

- **Model choice:** Reflect is driven by structured tool calls and fails loudly if the model or transport can't do tool calling, so Hindsight's model must support tool use, whatever the provider. [source](https://hindsight.vectorize.io/developer/api/reflect) Pick it from the Hindsight model leaderboard. [source](https://hindsight.vectorize.io/faq)
- **Client:** `hindsight-client` pinned in `pyproject.toml`; one async client created at app startup and closed on shutdown (`aclose()`).
- **Agent skill:** `npx skills add vectorize-io/hindsight-skills --skill hindsight-docs` in the repo, referenced from AGENTS.md. [source](https://github.com/vectorize-io/hindsight-skills)
- **Health:** `GET /api/health` calls a cheap bank-stats request with a 2 s timeout.

## memory\_service interface

Services call only these functions; each hides SDK details, builds tags through `tags.py`, and returns schema types, never raw SDK objects.

| Function | Used by | Hindsight call | Returns |
| --- | --- | --- | --- |
| `ensure_bank()` | app startup, seed | create/update bank with `BANK_CONFIG` | None |
| `ensure_mental_models(accounts)` | startup, seed | create mental models if missing | None |
| `retain_meeting(*, meeting_id, account_id, contact_ids, meeting_date, title, transcript, source="ingest")` | ingest | retain one document, id `meeting-<id>` | None |
| `retain_note(*, text, scope_type, scope_id)` | ask | retain item with scope tags + `kind:note` | None |
| `retain_preference(sentence)` | preferences | retain item tagged `kind:preference` | None |
| `recall_facts(*, query, tags, fact_kind=None)` | brief | recall, `all_strict` tags, budget `mid` | `list[MemoryHit]` |
| `reflect_structured(*, query, tags, schema, budget="mid")` | brief, reasoning, ask | reflect with `response_schema`, `include_facts=True`, `any_strict` tags, caller-supplied `budget` | `ReflectResult` |
| `get_mental_model(name)` | brief | read mental model | `MentalModelText \| None` |
| `timeline(contact_id)` | contacts API | recall scoped to `contact:<id>`, sorted by date | `list[MemoryHit]` |
| `wait_until_idle(timeout_s)` | seed, golden tests | poll bank stats until no pending operations | bool |

```python
class MemoryHit(BaseModel):
    memory_id: str
    text: str
    meeting_id: str | None      # from document metadata
    meeting_date: date | None
    tags: list[str]

class ReflectResult(BaseModel):
    text: str                    # markdown answer
    structured: dict | None      # structured_output
    sources: list[MemoryHit]     # from based_on.memories
    structured_error: str | None # structured_output_error
```

## Bootstrap

The bank and mental models are created explicitly at startup and by the seed script, so config is never left to Hindsight's auto-created defaults.

1. `ensure_bank()` creates or updates `ae-priya` with `BANK_CONFIG` (the `fact_kind` entity label). A bank used before creation is auto-created with default settings, which would skip our labels. [source](https://hindsight.vectorize.io/developer/api/memory-banks)
2. `ensure_mental_models()` creates one relationship model per account and one style model for the user, using the questions and tags in the schemas doc.
3. Seed script order: `ensure_bank` → retain all 15 seeded transcripts in date order → `wait_until_idle(600)` → `ensure_mental_models` → trigger a refresh → `wait_until_idle(300)`.
4. `make reset-demo` deletes the SQLite file and the `ae-priya` bank, then reruns the seed. The AMI test bank `ami-test` is never touched.

## Operation recipes

Fixed parameters per call site, so every agent uses the same budgets, tag modes and options.

| Call site | Operation | Tags, `tags_match` | Budget | Other options |
| --- | --- | --- | --- | --- |
| Ingest transcript | retain document | account, contacts, meeting, `kind:transcript` | — | stable id `meeting-<id>`, metadata |
| Personal touchpoints | recall | `contact:<id>`, `fact_kind:personal`, `all_strict` | mid | anchor time to `DEMO_TODAY` |
| Watch-outs | recall | `account:<id>`, `fact_kind:competitor`, `all_strict` | mid | anchor time to `DEMO_TODAY` |
| Unresolved objections | reflect | `account:<id>`, `any_strict` | mid | `response_schema`, `include_facts=True` |
| Contradictions after ingest | reflect | `account:<id>`, `any_strict` | high | `response_schema`, `include_facts=True` |
| Cross-contact gaps | reflect | `account:<id>`, `any_strict` | mid | `response_schema`, `include_facts=True` |
| Cross-deal patterns | reflect | `fact_kind:objection`, `any_strict` (all accounts) | high | `response_schema`, `include_facts=True` |
| Ask panel | reflect | scope tags, `any_strict` | mid | prior Q&A written into the query text; `include_facts=True` |
| Contact timeline | recall | `contact:<id>`, `any_strict` | low | sort by `meeting_date` |

**Why these settings:**

- Strict tag modes (`any_strict`, `all_strict`) return only matching tagged data; the non-strict modes also include untagged data. [source](https://hindsight.vectorize.io/developer/api/reflect)
- Reflect's budget defaults to `low`; `high` explores deeper and suits multi-source synthesis like contradictions and patterns. [source](https://hindsight.vectorize.io/developer/api/reflect)
- With `response_schema`, reflect returns `structured_output` in addition to the markdown `text`; a failed extraction is reported in `structured_output_error` while the call still succeeds. [source](https://hindsight.vectorize.io/developer/api/reflect)
- `include_facts=True` adds `based_on`, listing the memories actually used, each with `id`, `text`, `type` and occurrence times; these become our citations. [source](https://hindsight.vectorize.io/developer/api/reflect)
- Reflect has no separate context field; the docs say to put situational context in the query itself, so Ask history is prepended to the question. [source](https://hindsight.vectorize.io/developer/api/reflect)
- The MCP docs list a `query_timestamp` on recall that anchors relative time expressions and recency scoring; use the SDK equivalent with `DEMO_TODAY` if it exists. [source](https://hindsight.vectorize.io/developer/mcp-server)

**Contradiction schema** (passed as `response_schema`):

```python
class Contradiction(BaseModel):
    topic: str                 # "budget"
    earlier_value: str         # "about $40K"
    earlier_date: date
    new_value: str             # "closer to $75K"
    new_date: date
    summary: str               # one sentence for the alert

class ContradictionReport(BaseModel):
    contradictions: list[Contradiction]
```

## Failure handling

Every Hindsight failure becomes a typed error the API maps to `memory_unavailable`; nothing silently falls back to a memory-less answer in `memory` mode.

| Situation | Handling |
| --- | --- |
| Hindsight unreachable or timeout (recall 5 s, reflect 45 s, retain 30 s) | Raise `MemoryUnavailable` → HTTP 503 `memory_unavailable` |
| Reflect returns 500 (a retrieval tool failed or the model gave no answer) | Retry once after 2 s, then `MemoryUnavailable`. The docs say reflect fails rather than answering without evidence. [source](https://hindsight.vectorize.io/developer/api/reflect) |
| `structured_output_error` present | Retry once; if it persists, drop that brief section and log it. The docs call this field retryable. [source](https://hindsight.vectorize.io/developer/api/reflect) |
| Reflect found nothing relevant | Not an error: empty section, or the Ask "nothing in memory" reply |
| Provider 429 inside Hindsight (any provider) | Surfaces as slow or failed operations; seed script retains one at a time with backoff |
| Retain still processing when a brief is requested | Brief proceeds; the UI shows "memory still updating" while the ingest job is pending |
| Container restarted mid-operation | Stable `HINDSIGHT_API_WORKER_ID` prevents stuck operations. [source](https://hindsight.vectorize.io/faq) |

**Read-after-write:** retain can finish processing after the call returns, so anything that reads straight after writing (seed script, golden tests, the live M6 flow) calls `wait_until_idle` first. The MCP docs describe retain as asynchronous with a separate blocking variant; use the SDK's blocking option if it has one. [source](https://hindsight.vectorize.io/developer/mcp-server)

## Testing

Unit tests never touch Hindsight; golden tests always use the real server.

- **`FakeMemoryService`** (`tests/fakes/`): same interface; stores retained items in memory; `recall_facts` filters by tags and simple keyword match; `reflect_structured` returns canned `ReflectResult`s registered per test. Used by all service unit tests.
- **Contract test:** a small live test (marked `@pytest.mark.live`) retains one document, waits until idle, recalls it by tag, and reflects with a tiny schema. Run it first whenever the SDK version changes.
- **Golden tests:** seed the full fixture into a throwaway bank (`ae-test-<uuid8>`), wait until idle, generate the M6 brief, assert the six story beats, then delete the bank.
- **Debugging:** the Hindsight UI on port 9999 shows the bank's memories; reflect's `include_tool_calls` trace explains odd answers.

## Sources

- [Hindsight Reflect API](https://hindsight.vectorize.io/developer/api/reflect)
- [Hindsight Memory Banks](https://hindsight.vectorize.io/developer/api/memory-banks)
- [Hindsight MCP Server](https://hindsight.vectorize.io/developer/mcp-server)
- [Hindsight FAQ](https://hindsight.vectorize.io/faq)
- [Hindsight agent skills](https://github.com/vectorize-io/hindsight-skills)
