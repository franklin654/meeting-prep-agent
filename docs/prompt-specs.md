# Meeting Prep Agent — Prompt Specs

Sep 28, 2026 · @Thomas

Companion to [Data Model & Schemas](https://claude.ai/code/artifact/2a411140-fa53-434d-b52d-2261eba4b678) and the [Hindsight Integration Spec](https://claude.ai/code/artifact/a53e77ef-525b-4f57-b665-9170486263eb). Each prompt below is one file in `backend/app/llm/prompts/`; `{placeholders}` are filled by code.

## Prompt inventory

Four app LLM prompts, five Hindsight reflect queries, and one offline generator prompt.

| ID | File | Runs via | Called from | Output |
| --- | --- | --- | --- | --- |
| P1 | `extract_meeting.md` | LLM client `complete_json` | ingest | `MeetingExtraction` |
| P2 | `match_acknowledgements.md` | LLM client `complete_json` | ingest | `AckMatches` |
| P3 | `assemble_brief.md` | LLM client `complete_json` | brief | `BriefDraft` |
| P4 | `suggest_questions.md` | LLM client `complete_json` | brief (for Ask panel) | `SuggestedQuestions` |
| R1 | `reflect_objections.md` | Hindsight reflect | brief | `ObjectionReport` |
| R2 | `reflect_contradictions.md` | Hindsight reflect | reasoning (after ingest) | `ContradictionReport` |
| R3 | `reflect_cross_contact.md` | Hindsight reflect | brief | `GapReport` |
| R4 | `reflect_patterns.md` | Hindsight reflect | brief | `PatternReport` |
| R5 | `reflect_ask.md` | Hindsight reflect | ask | `ReflectAnswer` |
| G1 | `generate_transcript.md` | LLM client `complete_text`, offline script | `data/scripts/generate.py` | plain text transcript |

Preference memories are template sentences, not prompts (see Supporting prompts).

## Extraction prompts

P1 turns a transcript into structured facts for the ledger and the "learned" toast; P2 decides which open commitments the new meeting closed.

### P1 extract\_meeting.md

```markdown
You extract facts from a sales meeting transcript for a CRM ledger.
Our company is {our_company}; our people are {our_people}.
Meeting: "{meeting_title}" on {meeting_date} with {account_name}.
Known contacts at this account: {known_contacts}   # name, aliases, role

Return JSON matching the schema. Rules:
- commitments: only explicit promises to do something ("I'll send", "we'll share").
  owner = "us" if one of our people promised, "them" otherwise.
  due_date: resolve relative dates ("by Friday") against {meeting_date}; null if none stated.
- acknowledgements: statements that something promised earlier was received or done
  ("thanks for the SOC 2 report").
- facts: objections, personal details, deal facts (budget, timeline, scope, process),
  competitors. One fact per item. No commitments here.
- deal_budget_usd: integer USD only if a number is stated; "about $40K" -> 40000.
- source_quote: copy the exact words from the transcript, at most 200 characters.
- Never infer facts that are not said. If unsure, leave it out.

Transcript:
{transcript}
```

**Example output (M4 excerpt):** `{"owner": "us", "owner_person": "Priya", "text": "Send revised pricing deck with pilot option", "due_date": "2026-09-03", "source_quote": "I'll get you a revised pricing deck with the pilot option by the 3rd"}`

### P2 match\_acknowledgements.md

```markdown
Decide which open commitments were fulfilled, based only on acknowledgements from
a new meeting.

Open commitments (id: text):
{open_commitments}

Acknowledgements from the meeting on {meeting_date}:
{acknowledgements}

Return {"closed": [{"commitment_id": "...", "acknowledgement_index": 0}]}.
Only match when the acknowledgement clearly refers to the same deliverable.
A complaint that something was NOT received is never a match.
```

```python
class AckMatch(BaseModel):
    commitment_id: str
    acknowledgement_index: int

class AckMatches(BaseModel):
    closed: list[AckMatch]
```

## Brief assembly prompt

P3 writes the brief only from a numbered evidence list; the same prompt runs in `no_memory` mode with the evidence list empty, so the side-by-side comparison is fair.

### P3 assemble\_brief.md

```markdown
You prepare {user_name}, an account executive at {our_company}, for a meeting.
Today is {today}. Meeting: "{meeting_title}" on {meeting_date} with {account_name}.
Attendees: {attendees}   # name, role

Evidence (the ONLY facts you may use; each has an id):
{evidence}
# e.g. [mem:8f2c] (Call on Jul 14, 2026) Rahul: daughter Ananya starts college in Pune in September
#      [led:cm_91ab] OPEN, OVERDUE: us -> Send revised pricing deck with pilot option, due 2026-09-03 (Call on Aug 27)
#      [mm:acc_finedge] Relationship summary: ...

User's brief style: {style_profile}

Write the brief as JSON with these sections: {section_keys}.
Rules:
- Every item must list the evidence_ids it relies on. No evidence, no item.
- Do not invent names, numbers, dates or promises. Use evidence wording for numbers.
- open_commitments: one item per OPEN ledger entry; OVERDUE ones get severity "critical".
- watch_outs and alerts: severity "warning".
- personal_touchpoints: phrase as a question to ask ("Ask Rahul how ...").
- agenda: 3-5 short talking points that address open items and objections.
- Keep each item under 30 words. Follow the style profile for length and emphasis.
- If the evidence list is empty, write a generic brief from the meeting title and
  attendee roles only, with evidence_ids empty.
```

**Evidence assembly (code, before the prompt):** mental model → recall hits per section → reflect outputs (objections, gaps, patterns) with their `based_on` ids → ledger rows → pinned Ask answers. Cap at 40 items, newest first within each group, to stay within provider context limits.

**Post-processing (code, after the prompt):** map `evidence_ids` to `Citation`s, drop unresolved ids, drop items left with no citations in `memory` mode, then apply `hidden_sections` and `section_order` from the style profile.

## Reflect queries

Reflect queries are questions, not instructions; Hindsight's agent searches memory and answers, so each query states exactly what to look for and what counts as an answer. Tags, budgets and `include_facts` follow the Hindsight Integration Spec's recipe table.

### R1 reflect\_objections.md

```markdown
Today is {today}. List every concern, objection or blocker raised by people at
{account_name} in our meetings, who raised it, and when. For each, say whether it
was later addressed or resolved in a meeting, and by what. Only include concerns
that are stated in the meetings.
```

```python
class Objection(BaseModel):
    concern: str; raised_by: str; raised_on: date
    resolved: bool; resolution: str | None
class ObjectionReport(BaseModel):
    objections: list[Objection]
```

### R2 reflect\_contradictions.md

```markdown
Today is {today}. A new meeting with {account_name} took place on {meeting_date}.
Compare what was said in that meeting with what was said in earlier meetings.
List facts whose value changed: budget, timeline, scope, decision date, decision
makers, requirements. Give the earlier value and date and the new value and date.
Ignore changes that were already discussed as changes before this meeting.
```

Output: `ContradictionReport` (defined in the Hindsight Integration Spec).

### R3 reflect\_cross\_contact.md

```markdown
Today is {today}. Upcoming meeting attendees from {account_name}: {attendees}.
For each concern that one person at {account_name} raised and that we answered,
list which of these attendees were NOT present when it was raised or answered,
based on meeting attendance and what was said.
```

```python
class Gap(BaseModel):
    concern: str; raised_by: str; answered_on: date | None
    not_heard_by: list[str]
class GapReport(BaseModel):
    gaps: list[Gap]
```

### R4 reflect\_patterns.md

```markdown
An account is at the {deal_stage} stage and has raised: {current_objections}.
Across our OTHER accounts, find meetings where a similar objection was raised, and
what response or material resolved it. Name the account and the resolving material.
Only include cases where the objection was clearly resolved.
```

```python
class Pattern(BaseModel):
    objection: str; other_account: str; what_worked: str; resolved_on: date
class PatternReport(BaseModel):
    patterns: list[Pattern]
```

### R5 reflect\_ask.md

```markdown
Today is {today}. The user is preparing for work with {scope_label}.
{history_block}   # "Earlier in this conversation: Q: ... A: ..." (max 3), or empty
Question: {question}
Answer only from what was said in our meetings and notes. If memory does not cover
the question, say so plainly and set confident to false.
```

Output: `ReflectAnswer` (Data Model & Schemas). History goes in the query because reflect takes situational context in the query itself.

## Supporting prompts

The suggested-questions prompt and the offline transcript generator; preferences use fixed templates so the style memory stays clean.

### P4 suggest\_questions.md

```markdown
Based on this meeting brief, write 3 short questions the user might ask their memory
to prepare further. Each must be answerable from past meetings with {account_name}.
Prefer questions about open objections, changed facts and people not yet met.
Brief: {brief_json}
```

```python
class SuggestedQuestions(BaseModel):
    questions: list[str] = Field(min_length=1, max_length=3)
```

### Preference templates (no LLM)

| Feedback action | Sentence retained with `kind:preference` |
| --- | --- |
| `collapsed` | "On {date} the user collapsed the {section\_title} section of a meeting brief." |
| `up` | "On {date} the user found the {section\_title} section useful." |
| `down` | "On {date} the user found the {section\_title} section not useful." |
| `more` | "On {date} the user asked for more detail in {section\_title}." |
| `less` | "On {date} the user asked for less detail in {section\_title}." |

The style profile is derived in code from `Feedback` rows (for example, collapsed twice → hidden); the user mental model gives the plain-language `notes` shown in the UI.

### G1 generate\_transcript.md (offline)

```markdown
Write a realistic transcript of a sales meeting.
Date: {date}. Title: {title}. Duration about {minutes} minutes.
Participants and voices: {cast}   # from the Synthetic Data Spec contacts table
Story so far: {previous_summaries}
Style examples of natural speech (tone only, do not copy content): {style_refs}

The transcript MUST include each of these facts once, said naturally by the named
speaker, with numbers and dates exactly as given:
{required_facts}
It must NOT mention: {forbidden}

Format: one utterance per line:
[{date}T<hh:mm:ss>+05:30] <Full Name> (<Role>, <Company>): <words>
Include greetings, small talk, filler words, interruptions, one tangent, and a
next-steps wrap-up. Write the meeting at its natural length; do not shorten it or pad it.
```

## Prompt rules and testing

Prompts are code: versioned, tested, and changed only together with their output schema.

- [ ] Every prompt file starts with a header comment: ID, output model, temperature
- [ ] Temperatures: P1, P2 at 0; P3, P4 at 0.3; G1 at 0.8; reflect uses Hindsight's own settings
- [ ] Placeholders are filled with `str.format`-style keys only; no f-strings inside prompt files
- [ ] Output schemas are sent as JSON schema through the selected provider's mechanism (openai structured outputs / JSON mode, groq JSON mode, anthropic forced tool call with `input_schema`) and re-validated with Pydantic
- [ ] A prompt change reruns its fixture tests before merging

| Prompt | Fixture test |
| --- | --- |
| P1 | M4 transcript → contains the pricing-deck commitment due 2026-09-03 and the DAG-configs commitment |
| P2 | M5 acknowledgements → closes the DAG-configs commitment, not the pricing deck |
| P3 | M6 evidence → overdue deck item is `critical`; no item lacks evidence ids |
| R2 | After live M6 → one budget contradiction, $40K on Jul 28 to $75K on Sep 29 |
| R3 | Before M6 → a gap for the security concern with Anita in `not_heard_by` |
| R4 | Before Veda V4 → a pattern citing Nimbus and the trust portal + pen-test summary |
| R5 | "What did Anita say about budget?" → grounded answer citing M2; "What is Rahul's favourite food?" → ungrounded reply |
