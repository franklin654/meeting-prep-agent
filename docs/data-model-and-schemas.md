# Meeting Prep Agent — Data Model & Schemas

Sep 28, 2026 · @Thomas

Companion to the [Technical design](https://claude.ai/code/artifact/86a1a2be-764c-42ed-acd9-8f4a5dd6ca4c) and [Synthetic data spec](https://claude.ai/code/artifact/73444de8-7dd7-4429-9beb-832c8da71d9c). These models are the contract between modules: agents copy them into `backend/app/schemas/` as written.

## Conventions

String IDs with type prefixes, ISO dates, `str` enums, and snake\_case everywhere.

- **IDs:** readable prefixed strings: `acc_finedge`, `c_rahul`, `m4_finedge`, `cm_<uuid8>` (commitment), `br_<uuid8>` (brief), `ask_<uuid8>`, `job_<uuid8>`. Seed data uses readable IDs; runtime-created rows use the uuid form.
- **Dates:** `date` as `YYYY-MM-DD`; timestamps as ISO 8601 with offset (`2026-08-27T10:02:15+05:30`). "Today" always comes from `settings.demo_today`, never `date.today()`.
- **Money:** integer USD (`40000`), never floats or strings like "$40K".
- **Enums:** Python `StrEnum`, values lowercase snake\_case, shared by API, DB and prompts.
- **Models:** Pydantic v2 `BaseModel` with `model_config = ConfigDict(extra="forbid")` for all LLM outputs, so unexpected fields fail validation.

```python
class FactKind(StrEnum):
    commitment = "commitment"; objection = "objection"; personal = "personal"
    deal_fact = "deal_fact"; competitor = "competitor"

class Owner(StrEnum):
    us = "us"; them = "them"

class CommitmentStatus(StrEnum):
    open = "open"; done = "done"

class ScopeType(StrEnum):
    account = "account"; contact = "contact"; meeting = "meeting"
```

## Extraction output

One LLM call per ingested transcript returns `MeetingExtraction`; it feeds entity resolution and the commitments ledger only, since Hindsight gets the raw transcript.

```python
class PersonMention(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name_as_said: str            # "KS", "Rahul", "their CFO"
    role_if_stated: str | None
    organisation: str | None     # "FinEdge", "Tracewise"

class ExtractedCommitment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner: Owner
    owner_person: str            # name_as_said of who promised
    text: str                    # "Send revised pricing deck with pilot option"
    due_date: date | None        # resolved against meeting date; None if not stated
    source_quote: str            # exact words from transcript, <= 200 chars

class Acknowledgement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str             # "SOC 2 report received"
    source_quote: str

class ExtractedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: FactKind               # never "commitment" here; those go above
    about_person: str | None
    text: str
    source_quote: str

class MeetingExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    people: list[PersonMention]
    commitments: list[ExtractedCommitment]
    acknowledgements: list[Acknowledgement]   # used to close open commitments
    facts: list[ExtractedFact]                # shown in the "learned" toast
    deal_budget_usd: int | None               # only if a number is stated
```

**Rules:** `source_quote` must appear verbatim in the transcript (checked in code; failing items are dropped). Matching an `Acknowledgement` to an open commitment is a second, small LLM call given only the open commitments' texts and the acknowledgements.

## Brief output

The LLM returns a `BriefDraft` that points at evidence IDs it was given; code turns those IDs into `Citation` objects and drops anything it can't resolve, producing the stored `Brief`.

```python
class SectionKey(StrEnum):
    attendees = "attendees"; where_left_off = "where_left_off"
    open_commitments = "open_commitments"; unresolved_objections = "unresolved_objections"
    personal_touchpoints = "personal_touchpoints"; agenda = "agenda"
    watch_outs = "watch_outs"; alerts = "alerts"; your_questions = "your_questions"

class Severity(StrEnum):
    info = "info"; warning = "warning"; critical = "critical"   # neutral / amber / red

# ---- what the LLM returns ----
class DraftItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    severity: Severity = Severity.info
    contact_ids: list[str] = []
    evidence_ids: list[str]      # ids from the evidence list in the prompt

class BriefDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sections: dict[SectionKey, list[DraftItem]]

# ---- what the API returns and the DB stores ----
class SourceType(StrEnum):
    meeting = "meeting"; ledger = "ledger"; mental_model = "mental_model"; ask = "ask"

class Citation(BaseModel):
    source_type: SourceType
    meeting_id: str | None
    meeting_date: date | None
    label: str                   # "Call on Aug 27, 2026"
    quote: str | None            # short supporting text, <= 200 chars
    memory_id: str | None        # Hindsight memory id when available

class BriefItem(BaseModel):
    id: str
    text: str
    severity: Severity
    contact_ids: list[str]
    citations: list[Citation]

class BriefSection(BaseModel):
    key: SectionKey
    title: str
    items: list[BriefItem]
    collapsed: bool = False      # from style profile

class Brief(BaseModel):
    id: str
    meeting_id: str
    mode: Literal["memory", "no_memory"]
    generated_at: datetime
    sections: list[BriefSection] # ordered by style profile
    facts_used: int              # personalization meter
    preferences_applied: list[str]
```

**Evidence IDs in the prompt:** `mem:<hindsight_id>`, `led:<commitment_id>`, `mm:<mental_model_id>`, `ask:<ask_id>`. **Validation:** in `memory` mode every `BriefItem` has at least one citation; in `no_memory` mode citations are empty by design and the UI labels the brief "No memory".

## Ask panel

The Ask flow uses reflect with a response schema; the API wraps the result with citations mapped the same way as the brief.

```python
class AskTurn(BaseModel):
    question: str
    answer: str

class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    scope_type: ScopeType
    scope_id: str
    history: list[AskTurn] = Field(default_factory=list, max_length=3)

# response_schema passed to Hindsight reflect
class ReflectAnswer(BaseModel):
    answer: str
    confident: bool              # false when memory doesn't cover the question

class AskResponse(BaseModel):
    ask_answer_id: str
    answer: str                  # replaced by the fixed "nothing in memory" text when ungrounded
    grounded: bool               # true only if citations is non-empty and confident
    citations: list[Citation]

class PinRequest(BaseModel):
    meeting_id: str

class NoteRequest(BaseModel):
    text: str = Field(min_length=3, max_length=1000)
    scope_type: ScopeType
    scope_id: str
```

The fixed ungrounded reply is `"Nothing in memory covers that yet."`, defined once in `schemas/ask.py`.

## Hindsight model

One bank per user, a fixed tag vocabulary built only by `memory/tags.py`, and a `fact_kind` entity label that turns each extracted fact into a filterable tag. SDK call shapes below match `hindsight-client` 0.10.1 (checked with `inspect.signature`); the client is async, so calls are `aretain`, `arecall`, `areflect`.

### Bank config

```python
BANK_ID = f"ae-{settings.demo_user_id}"   # "ae-priya"

BANK_CONFIG = {
    "entity_labels": [{
        "key": "fact_kind",
        "type": "text",
        "tag": True,          # each extracted label is also written as a tag
        "description": (
            "What kind of sales-meeting fact this is. One of: commitment (a promise "
            "with an owner), objection (a concern or blocker), personal (life detail "
            "someone shared), deal_fact (budget, timeline, scope, stage, process), "
            "competitor (another vendor mentioned)."
        ),
    }],
}
```

The Hindsight FAQ shows `entity_labels` with `key`, `type`, `tag` and `description`, and says labels with `tag: true` are written as `key:value` tags. [source](https://hindsight.vectorize.io/faq) If the SDK supports an explicit allowed-values list for a label, use it with the five values above instead of relying on the description.

### Tag vocabulary

| Tag | Written when | Example |
| --- | --- | --- |
| `account:<id>` | Every transcript and note for an account | `account:acc_finedge` |
| `contact:<id>` | Once per attendee on a transcript; on contact-scoped notes | `contact:c_anita` |
| `meeting:<id>` | Every transcript; meeting-scoped notes | `meeting:m4_finedge` |
| `kind:transcript` \| `kind:note` \| `kind:preference` | Every retain | `kind:preference` |
| `fact_kind:<value>` | Automatically, by the entity label | `fact_kind:commitment` |

### Retain payloads

```python
# transcript: one document per meeting, stable id => re-ingest replaces it
await client.aretain(
    bank_id=BANK_ID,
    content=transcript_text,                    # timestamped, speaker-prefixed lines
    document_id="meeting-m4_finedge",
    tags=["account:acc_finedge", "contact:c_rahul", "contact:c_karan",
          "meeting:m4_finedge", "kind:transcript"],
    metadata={"meeting_id": "m4_finedge", "meeting_date": "2026-08-27",
              "title": "Pilot scoping", "source": "seed"},
    timestamp=datetime(2026, 8, 27),
    context="sales meeting transcript",
)

# preference: short sentence, no account tag
await client.aretain(
    bank_id=BANK_ID,
    content="On 2026-09-28 the user collapsed the personal touchpoints section.",
    tags=["kind:preference"],
    context="brief feedback",
)
```

### Recall plan per brief section

| Section | Operation | Tags filter |
| --- | --- | --- |
| where\_left\_off | account mental model | — |
| personal\_touchpoints | recall | `contact:<attendee>` + `fact_kind:personal` (strict) |
| watch\_outs | recall | `account:<id>` + `fact_kind:competitor` (strict) |
| unresolved\_objections | reflect, `response_schema` | `account:<id>` |
| alerts (contradictions, cross-contact gaps) | reflect, `response_schema` | `account:<id>` |
| cross-deal patterns | reflect across all accounts | `fact_kind:objection` |
| style | user mental model | `kind:preference` |

Open commitments come from the SQLite ledger, not recall, so overdue logic stays exact.

### Mental models

- Per account: "What is the current state of our relationship with {account\_name}: stage, key people, open issues?" scoped to `account:<id>`.
- Per user: "How does this user like their meeting briefs: length, sections to emphasise or hide, tone?" scoped to `kind:preference`.

## SQLite tables

Nine SQLModel tables; JSON columns hold nested Pydantic data (brief content, answers), and nothing about memory itself is stored here.

```python
class Account(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    industry: str
    size: int | None = None
    stage: str                           # discovery | evaluation | closed_won | closed_lost
    deal_value_usd: int | None = None

class Contact(SQLModel, table=True):
    id: str = Field(primary_key=True)
    account_id: str | None = Field(foreign_key="account.id")  # None for our own people
    name: str
    aliases: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    role: str | None = None
    needs_review: bool = False           # created by entity resolution, unconfirmed

class Meeting(SQLModel, table=True):
    id: str = Field(primary_key=True)
    account_id: str = Field(foreign_key="account.id", index=True)
    title: str
    scheduled_at: datetime
    status: str                          # upcoming | done
    transcript: str | None = None
    ingested_at: datetime | None = None

class MeetingAttendee(SQLModel, table=True):
    meeting_id: str = Field(foreign_key="meeting.id", primary_key=True)
    contact_id: str = Field(foreign_key="contact.id", primary_key=True)

class Commitment(SQLModel, table=True):
    id: str = Field(primary_key=True)
    account_id: str = Field(foreign_key="account.id", index=True)
    meeting_id: str = Field(foreign_key="meeting.id")
    owner: Owner
    contact_id: str | None = Field(default=None, foreign_key="contact.id")
    text: str
    due_date: date | None = None
    status: CommitmentStatus = CommitmentStatus.open
    source_quote: str
    closed_by_meeting_id: str | None = None

class BriefRecord(SQLModel, table=True):
    id: str = Field(primary_key=True)
    meeting_id: str = Field(foreign_key="meeting.id", index=True)
    mode: str                            # memory | no_memory
    content: dict = Field(sa_column=Column(JSON))   # Brief.model_dump(mode="json")
    created_at: datetime

class Feedback(SQLModel, table=True):
    id: str = Field(primary_key=True)
    brief_id: str = Field(foreign_key="briefrecord.id")
    section: SectionKey
    action: str                          # up | down | more | less | collapsed
    created_at: datetime

class AskAnswer(SQLModel, table=True):
    id: str = Field(primary_key=True)
    scope_type: ScopeType
    scope_id: str
    question: str
    answer: dict = Field(sa_column=Column(JSON))    # AskResponse minus id
    pinned_to_meeting_id: str | None = Field(default=None, foreign_key="meeting.id")
    created_at: datetime

class Job(SQLModel, table=True):
    id: str = Field(primary_key=True)
    kind: str                            # ingest | note | reasoning
    status: str                          # pending | done | failed
    result: dict | None = Field(default=None, sa_column=Column(JSON))
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None
```

Overdue is computed, never stored: `status == open and due_date < settings.demo_today`.

## API models, jobs and errors

Request and response bodies for the endpoints in the Technical design; routes return these models directly so the OpenAPI spec, and the generated frontend client, stay exact.

```python
class ContactRef(BaseModel):
    id: str; name: str; role: str | None

class MeetingSummary(BaseModel):          # GET /api/meetings
    id: str; account_id: str; account_name: str; title: str
    scheduled_at: datetime; status: str
    attendees: list[ContactRef]
    brief_ready: bool

class NotesRequest(BaseModel):            # POST /api/meetings/{id}/notes
    transcript: str = Field(min_length=50)

class JobAccepted(BaseModel):             # 202 responses
    job_id: str

class LearnedSummary(BaseModel):
    facts: list[str]                      # "Budget now $75K (was $40K)"
    new_commitments: int
    closed_commitments: int
    alerts: list[str]

class JobStatus(BaseModel):               # GET /api/jobs/{id}
    id: str; kind: str
    status: Literal["pending", "done", "failed"]
    learned: LearnedSummary | None = None
    error: str | None = None

class TimelineEntry(BaseModel):           # GET /api/contacts/{id}/timeline
    text: str
    fact_kind: FactKind | None
    learned_on: date
    citation: Citation

class ContactTimeline(BaseModel):
    contact: ContactRef
    entries: list[TimelineEntry]          # newest first

class FeedbackRequest(BaseModel):         # POST /api/briefs/{id}/feedback
    section: SectionKey
    action: Literal["up", "down", "more", "less", "collapsed"]

class StyleProfile(BaseModel):
    section_order: list[SectionKey]
    hidden_sections: list[SectionKey]
    length: Literal["short", "standard", "detailed"]
    notes: list[str]                      # plain-language rules shown in the UI

class Nudge(BaseModel):                   # GET /api/nudges
    kind: Literal["overdue_commitment", "silent_contact", "brief_ready"]
    text: str
    link: str                             # frontend route

class ErrorBody(BaseModel):
    code: str
    message: str

class ErrorResponse(BaseModel):
    error: ErrorBody
```

| Error code | HTTP | When |
| --- | --- | --- |
| `not_found` | 404 | Unknown meeting, contact, brief or job |
| `validation_error` | 422 | Request body fails its model |
| `memory_unavailable` | 503 | Hindsight unreachable or timing out |
| `llm_timeout` | 504 | LLM call exceeded 30 s |
| `llm_invalid_output` | 502 | LLM output failed validation after one retry |
| `rate_limited` | 429 | LLM provider (app or Hindsight) returned 429 after retries |

## Change rules

This doc is the source of truth for every model; where the Technical design's table summary differs (it omits `Job` and some commitment columns), this doc wins.

- [ ] A schema change updates this doc, the Pydantic or SQLModel class, and the generated frontend client in the same PR
- [ ] Enum values are never renamed once seeded; add new values instead
- [ ] LLM-facing models (`MeetingExtraction`, `BriefDraft`, `ReflectAnswer`) change only together with their prompt file
- [ ] Tag strings are built only through `memory/tags.py`; a new tag prefix is added to the vocabulary table first
- [ ] SQLite is dev-only: on schema change, run `make reset-demo` rather than writing migrations

## Sources

- [Hindsight FAQ](https://hindsight.vectorize.io/faq) (entity labels, tags, retain format)
