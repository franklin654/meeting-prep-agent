# Meeting Prep Agent — Feature & Requirements Spec

Sep 28, 2026 · @Thomas

## Overview

We are building a Meeting Prep Agent for one persona and one workflow: a B2B sales rep preparing for prospect calls, with Hindsight memory at the center.

- **Persona:** A B2B Account Executive (e.g. "Priya, AE at a mid-size SaaS company") managing 15–30 active deals, each with several calls over weeks.
- **Workflow:** Before every call, the agent produces a one-screen brief. After the call, it ingests notes or a transcript and updates memory.
- **Value proposition:** Walk into every meeting knowing everything ever discussed, promised or missed with this person, without re-reading a single note.
- **$50/month test:** A rep who loses one deal a quarter to a forgotten promise or a repeated question would pay for this. Gong and Clari already sell parts of it, which supports the business case.

Scope rule: anything about getting data in or pushing output out gets the simplest possible version. Build time goes to what happens inside memory, where 55% of the score (Innovation + Hindsight Memory) sits.

## Core features (P0, must ship)

Eleven features across four groups make up the minimum demoable product; group D is what the 25% memory criterion rewards most directly.

### A. Interaction ingestion (writing to memory)

1. **Post-meeting capture.** Paste or upload a transcript or rough notes, or dictate a quick summary. The agent extracts structured facts and stores them.
2. **Structured extraction.** Each meeting becomes typed memories:
   - People and roles ("Rahul, VP Eng, is the technical decision maker")
   - Topics discussed
   - Commitments by both sides, with owner and due date
   - Objections and concerns ("worried about SOC 2 compliance")
   - Personal details shared ("daughter starting college in September")
   - Deal facts: budget, timeline, competitors, stage
   - Sentiment and tone
3. **Entity resolution.** "Rahul", "Rahul M." and "their VP of Engineering" resolve to one contact; every memory ties to a contact and an account.

### B. Pre-meeting brief (reading from memory)

4. **One-click brief.** Select an upcoming meeting and get a brief with these sections:
   - Who you're meeting: role, history, last interaction per attendee
   - Where you left off: a 2–3 line relationship summary
   - Open commitments, both sides, overdue items in red
   - Unresolved objections
   - Personal touchpoints ("Ask how the college move went")
   - Suggested agenda and talking points
   - Watch-outs ("They mentioned a competitor on the Aug 12 call")
5. **Source citations on every claim.** Each point links to its originating meeting ("from call on Aug 12, 2026"). This makes memory visible and builds trust.
6. **Missed follow-up detection.** "You promised a pricing deck on Sept 3. There's no record you sent it."

### C. Preference learning (memory about the user)

7. **Brief style adaptation.** If the user always collapses personal touchpoints, the section shrinks; if they keep asking about competitors, it expands. Length, tone and bullets vs narrative are learned too.
8. **Explicit feedback loop.** Thumbs up/down or "more / less of this" per section, stored as preference memories.

### D. Memory showcase

9. **With vs without memory toggle.** The same meeting briefed side by side by a stateless LLM and by the memory agent. This is the strongest 10-second demo moment.
10. **Memory timeline / inspector.** Shows what the agent knows about a contact, when it learned each fact, and from which meeting.
11. **Learning curve indicator.** Meeting 1 is generic, meeting 5 personalized, meeting 10 anticipates needs; e.g. "Brief personalization: 12 facts used · 3 preferences applied".

## Differentiators (P1, strongly recommended)

These seven features carry the 30% Innovation score by showing reasoning over memory, not just retrieval.

12. **Contradiction and change detection.** "Budget was $40K in the July call; today they said $75K. Scope may have expanded."
13. **Cross-contact intelligence.** "Rahul (VP Eng) raised security concerns, but Anita (CFO) has never heard your security answer."
14. **Stakeholder map.** An auto-built org chart per account: champion, blocker, gone silent.
15. **Relationship health signal.** Response delays, sentiment trend, and commitments kept vs missed.
16. **Pattern learning across deals.** "In 3 past deals the SOC 2 objection appeared at stage 2. Here's the answer that worked with Acme."
17. **Proactive nudges.** Daily digest: 2 overdue commitments, 1 contact silent for 21 days, 3 briefs ready for tomorrow.
18. **Ask panel (scoped memory Q&A).** A side panel on the Brief and Contact pages for free-form questions ("What did Anita say about Q4 budget?"), answered from memory with citations and scoped to that account or contact. Any answer can be pinned to the brief as an extra section. Questions are not retained; only an explicit "Remember this" note is. It is a companion to the brief, not the main interface, which keeps the project out of plain-chatbot territory.

## Nice-to-have (P2, only if time allows)

19. Post-meeting follow-up email drafted from memory (commitments, tone preferences).
20. Voice input for the post-call debrief ("Rahul was happy, wants a demo next week, I owe him the case study").
21. Transcript import from Otter or Fireflies files.
22. One-way Slack notification: "Your brief for the 3 PM FinEdge call is ready", or the daily nudge digest.
23. Calendar and Gmail connectors for real-world ingestion.

## Memory architecture (Hindsight)

One memory bank per user holds four kinds of memory, fed by a write path after meetings and used by a read path and a reasoning path before them. Verify exact API names against the current Hindsight docs.

&#91;embedded content: memory architecture · write, read and reason paths\]

- **Bank and tagging:** One bank per AE; every memory tagged with contact, account and meeting ID so recall can be scoped.
- **Write path (retain):** After each meeting, validated structured facts are retained with timestamps. Preference signals from feedback are retained the same way.
- **Read path (recall):** Before a meeting, recall is scoped to attendees and account, mixing temporal ("last 3 interactions") and semantic ("any pricing concerns") queries.
- **Reasoning path (reflect):** Powers contradiction detection, relationship summaries and cross-deal patterns; conclusions are written back as observations.
- **Temporal awareness:** Every memory carries a timestamp, so the agent can say "3 weeks ago" and spot stale facts.
- **Supersede, don't overwrite:** A changed fact (e.g. new budget) keeps the old value as history. This is what powers contradiction detection.

## Technical requirements (20%)

Clean modules, validated memory writes and explicit edge-case handling are what judges probe for this criterion.

- **Architecture:** Separate modules for ingestion/extraction, memory service (Hindsight wrapper), brief generator, preference learner and UI.
- **Structured outputs:** JSON schemas for extraction; memory writes are validated before storing.
- **No-hallucination rule:** Every brief claim maps to a stored memory. Claims without a source are dropped; citations enforce this.
- **Idempotent ingestion:** Re-uploading the same transcript never duplicates memories.
- **Tests:** Extraction accuracy on sample transcripts and recall correctness on seeded scenarios.

### Edge cases

| Case | Expected behaviour |
| --- | --- |
| First meeting with a contact | Graceful fallback: "No history yet. Here's what we know about the company." |
| Two contacts with the same name | Disambiguate by account, or ask the user |
| Contradictory facts | Flag the change; keep both values with dates |
| Very long history (50+ meetings) | Summarize older meetings; prioritize recent and relevant |
| Empty or low-quality notes | Extract what's there; never invent |
| Several attendees, mixed histories | Per-attendee sections plus a shared account view |
| Commitment with no due date | Mark "undated" or infer a window, clearly labeled |

## User experience (15%)

Three screens, a brief readable in 60 seconds, and visible moments where the agent learns.

- **Screens:** (1) upcoming meetings dashboard, (2) brief view, (3) contact memory timeline.
- **Brief layout:** One screen, clear hierarchy, colour-coded alerts (red = overdue, amber = watch-out).
- **Logging:** One action after a meeting; paste and submit is enough.
- **Learning moments:** A toast such as "Learned: you prefer shorter briefs."
- **States:** Loading states and a clean empty state for new contacts.

## Synthetic data plan

Data is the biggest factor in looking real, so it gets its own owner and time budget. Generate with an LLM, then hand-edit for realism.

| Element | Spec |
| --- | --- |
| Our company | Fictional SaaS vendor (e.g. a data observability platform) with a clear product and pricing |
| Accounts | 3–5 prospects with realistic names, industries, sizes and deal values (e.g. ₹38L or $85K ARR) |
| Contacts | 8–12 people with distinct roles (VP Eng, CFO, Procurement, IT Security) and personalities |
| Meeting history | 5–10 meetings per hero account over 2–3 months, with small talk, objections, promises and competitor mentions |

### Planted story beats

- [ ] A promise made in meeting 2 that was never fulfilled
- [ ] A budget number that changes between meetings 3 and 6
- [ ] A personal detail mentioned once, weeks earlier
- [ ] A competitor mentioned in passing
- [ ] An objection raised by one stakeholder that another hasn't heard answered

## Demo storyline (60–90 seconds)

The demo tells one story: problem, generic answer, memory-powered answer, then the agent getting smarter live.

1. **The problem (10s):** "Priya has her sixth call with FinEdge tomorrow. She's had 40 other calls since the last one. What did she promise? What did the CFO worry about?"
2. **Without memory (10s):** A generic brief full of company-overview fluff.
3. **With memory (25s):** The overdue pricing deck, the budget change flagged, the college question, the unanswered security objection, each with a citation.
4. **It learns (15s):** Priya deletes the small-talk section and gives feedback. The next brief, for a different contact, adapts.
5. **It gets smarter (10s):** Log the new meeting; the memory timeline updates and a contradiction is caught live.
6. **Close:** "Every meeting makes the next one better."

## Real-world impact (10%)

The product has a clear buyer today and an obvious path from hackathon demo to team tool.

- **Target users:** Sales, customer success, consultants, recruiters, account managers.
- **Adoption path:** Chrome extension or calendar integration → CRM sync (Salesforce, HubSpot) → team-level shared memory.
- **Metrics to pitch:** Prep time per meeting (e.g. 15 minutes down to 1) and commitments kept.
- **Privacy:** Per-user memory isolation, a user-controlled "forget this", no recording without consent.

## Out of scope

Anything that only moves data in or out gets the simplest version; these are cut to protect polish.

| Item | Why it's out |
| --- | --- |
| Live in-call transcription | Happens during the meeting, not before or after it; needs streaming speech-to-text, diarization and Zoom/Teams bots; high demo risk; Otter and Fireflies already do it (we import their files instead, P2) |
| Two-way Slack / team features | Raises shared-memory and permission questions that dilute a single-persona demo (a one-way Slack nudge is allowed as P2) |
| Full CRM replacement | Adds breadth, not memory depth |
| Mobile app | No gain for judging criteria |
| Real email sending | Drafts only; sending adds auth and risk |

## Judging criteria mapping and build order

Every P0 and P1 feature earns points on at least one criterion; the build order gets a demoable product early and adds wow factor in layers.

| Criterion (weight) | Features that earn it |
| --- | --- |
| Innovation (30%) | Contradiction detection, cross-contact intelligence, cross-deal patterns, proactive nudges |
| Hindsight Memory (25%) | With/without toggle, memory inspector, Ask panel, preference learning, reflect-based reasoning, learning curve |
| Technical (20%) | Structured extraction, citations and no-hallucination rule, edge-case handling, clean modules |
| User Experience (15%) | 60-second brief, three-screen flow, visible learning moments, demo narrative |
| Real-world Impact (10%) | Sales persona, clear pricing logic, CRM adoption path |

### Build order

1. Ingestion and extraction
2. Hindsight retain and recall
3. Basic brief
4. Source citations
5. With/without memory toggle
6. Synthetic data with planted story beats
7. Preference learning
8. Contradiction detection
9. Memory timeline UI
