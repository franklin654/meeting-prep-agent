# Meeting Prep Agent — Synthetic Data Spec

Sep 28, 2026 · @Thomas

Companion to the [Feature spec](https://claude.ai/code/artifact/a88c5f23-38e8-43fe-a34f-7c4a0b485693) and [Technical design](https://claude.ai/code/artifact/86a1a2be-764c-42ed-acd9-8f4a5dd6ca4c).

## Purpose and principles

This spec defines 17 synthetic meetings across 4 accounts, built so the demo's story beats are guaranteed to exist and the golden tests have fixed facts to assert on.

- **Scripted, then generated:** Every fact that the demo or a test depends on is fixed here. The LLM writes only the talk around those facts.
- **One source of truth:** Names, dates, numbers and promises in this doc win over anything a generated transcript says.
- **Fixed clock:** The app reads `DEMO_TODAY=2026-09-28` so "overdue" and "3 weeks ago" give the same answer at every rehearsal.
- **Fictional everything:** All companies, people and competitors are invented. No real brands, to avoid judges wondering about real customer data.
- **Free-tier-friendly size:** Seeded transcripts have no target length: a minimum of 400 spoken words and a sanity cap of 6,000 only to catch runaway output, small enough to seed on the free tier.

## Our company and persona

The user is Priya Nair, an Account Executive at Tracewise, a fictional data observability platform selling to mid-size data teams.

| Item | Value |
| --- | --- |
| Vendor | Tracewise (data pipeline monitoring, lineage, incident alerts) |
| Plans | Growth: $36K/year up to 50 pipelines · Enterprise: from $75K/year, unlimited pipelines, SSO, India data residency |
| Pilot | 30-day paid pilot at $5K, credited on purchase |
| Trust assets | SOC 2 Type II report (under NDA), trust portal, annual pen-test summary |
| AE | Priya Nair, Bengaluru, 4 years in SaaS sales, 22 active deals |
| Sales engineer | Arjun Menon (joins technical calls) |
| Competitor | DataHawk (fictional), cheaper, no India data residency |

## Accounts

FinEdge is the hero account the demo follows; the other three give the dashboard realistic volume and supply the cross-deal patterns.

| ID | Account | Industry, size | Stage | Deal value | Meetings | Role in demo |
| --- | --- | --- | --- | --- | --- | --- |
| `acc_finedge` | FinEdge Payments (Mumbai) | Fintech, 600 staff | Evaluation | $40K → $75K | 5 seeded + 1 live | Hero: all story beats |
| `acc_nimbus` | Nimbus Logistics (Pune) | Logistics, 1,200 staff | Closed won (Jun 2026) | $62K | 4 | Source of the SOC 2 answer that worked |
| `acc_veda` | Veda Health (Hyderabad) | Healthtech, 350 staff | Discovery | $30K | 4 | Same SOC 2 objection at stage 2; a meeting on the dashboard |
| `acc_orbit` | Orbit Retail (Chennai) | E-commerce, 900 staff | Closed lost (Aug 2026) | $45K | 3 | Lost to DataHawk on price; warning pattern |

## Contacts

Thirteen contacts, each with a distinct voice so generated transcripts don't blur into one speaker.

| ID | Name | Account | Role | Deal role | Voice and traits |
| --- | --- | --- | --- | --- | --- |
| `c_priya` | Priya Nair | Tracewise | Account Executive | Our side | Our AE, Bengaluru, 4 years in SaaS sales, 22 active deals. Runs every call. |
| `c_rahul` | Rahul Mehta | FinEdge | VP Engineering | Technical decision maker | Direct, impatient with fluff, jokes about on-call pain |
| `c_anita` | Anita Desai | FinEdge | CFO | Economic buyer | Numbers-first, asks "what does this replace?", polite but brief |
| `c_karan` | Karan Shah | FinEdge | Data Platform Lead | Champion | Enthusiastic, over-shares, alias "KS" in notes |
| `c_sneha` | Sneha Iyer | FinEdge | IT Security Manager | Blocker until satisfied | Precise, cites RBI data rules, asks for documents |
| `c_vikram` | Vikram Rao | FinEdge | Procurement Manager | Gatekeeper (not met yet) | Mentioned only; appears in the live meeting's next steps |
| `c_meera` | Meera Kulkarni | Nimbus | Head of Data | Champion, signed | Warm, gives referrals |
| `c_deepak` | Deepak Joshi | Nimbus | CISO | Security approver | Was won over by the trust portal + pen-test summary |
| `c_farah` | Farah Siddiqui | Veda | Director of Engineering | Technical decision maker | Cautious, healthcare compliance focus |
| `c_nikhil` | Nikhil Reddy | Veda | Data Engineer | Champion | Hands-on, wants a sandbox |
| `c_lakshmi` | Lakshmi Pillai | Orbit | VP Data | Decision maker | Price-sensitive |
| `c_sameer` | Sameer Khan | Orbit | Finance Controller | Economic buyer | Pushed for DataHawk's price |
| `c_arjun` | Arjun Menon | Tracewise | Sales Engineer | Our side | Joins technical calls |

## FinEdge meeting timeline

Five seeded meetings from July 14 to September 15, 2026, then meeting 6 on September 29, the day after `DEMO_TODAY`. Each transcript must contain its required facts and nothing from later meetings.

| # | Date | Title | Attendees | Required facts |
| --- | --- | --- | --- | --- |
| M1 | 2026-07-14 | Discovery | Priya, Rahul, Karan | 3 pipeline incidents last quarter, one delayed a settlement report · current alerts are homegrown Airflow checks · about 40 pipelines · **Rahul's daughter Ananya starts college in Pune in September** · Priya promises a fintech case study by Jul 17 |
| M2 | 2026-07-28 | Budget and process | Priya, Karan, Anita | Karan thanks Priya for the case study (M1 promise done) · **Anita: budget is about $40K this fiscal year** · decision by Oct 31 · procurement runs through Vikram Rao · Anita asks "what does this replace?" · Anita mentions training for the Mumbai half marathon · Priya promises an ROI one-pager by Aug 5 |
| M3 | 2026-08-12 | Technical deep dive | Priya, Arjun, Rahul, Karan, Sneha | Rahul confirms ROI one-pager received · **Sneha: needs SOC 2 Type II and India data residency (RBI rules)** · **Karan: "we also had a look at DataHawk"** · pipeline count now 55 (above Growth plan limit) · Priya promises SOC 2 report under NDA by Aug 14 |
| M4 | 2026-08-27 | Pilot scoping | Priya, Arjun, Rahul, Karan | Rahul thanks Priya for the SOC 2 report · pilot on 10 pipelines, start by mid-October · **Priya promises a revised pricing deck with the pilot option by Sep 3** · Karan promises sample DAG configs by Sep 5 |
| M5 | 2026-09-15 | Check-in | Priya, Karan | Priya thanks Karan for the DAG configs · Rahul was out last week for his daughter's college move · Anita asked whether the payments-risk team could join the rollout · **Karan: Anita hasn't been in any of the security conversations** · Karan: "Rahul said he's still waiting on something from your side" (never named) · next call set for Sep 29 with Rahul, Anita, Karan |
| M6 | 2026-09-29 | Pilot decision (upcoming) | Priya, Rahul, Anita, Karan | Brief generated before it; transcript logged live on stage (see Live demo meeting) |

The pricing deck is never mentioned as received in any later meeting. Every other promise is explicitly acknowledged in the next meeting, which is how ingestion marks it done.

## Planted story beats

Six beats, each tied to a feature and to an exact expected output that a golden test asserts.

| Beat | Planted in | Feature shown | Brief for M6 must show |
| --- | --- | --- | --- |
| B1 Broken promise | M4 | Missed follow-up detection (6) | Overdue, red: "Revised pricing deck with pilot option, promised Aug 27, due Sep 3", cited to M4 |
| B2 Budget change | M2 (+ live M6) | Contradiction detection (12) | Before M6: budget "about $40K" cited to M2. After live M6: alert "$40K on Jul 28 → $75K on Sep 29" |
| B3 Personal detail | M1 (reinforced M5) | Personal touchpoints (4) | "Ask Rahul how Ananya's move to college in Pune went", cited to M1 and M5 |
| B4 Competitor | M3 | Watch-outs (4) | "FinEdge has looked at DataHawk", cited to M3 |
| B5 Security gap | M3 + M5 | Cross-contact intelligence (13) | "Sneha's SOC 2 and data-residency concerns were answered, but Anita hasn't heard them", cited to M3 and M5 |
| B6 Cross-deal pattern | Nimbus M2–M3, Veda M2 | Pattern learning (16) | "SOC 2 objections at this stage were resolved at Nimbus with the trust portal and pen-test summary", cited to Nimbus |

Distractor facts (Anita's half marathon, Karan's vague "waiting on something") test that the brief stays precise and doesn't overreach.

## Supporting account meetings

Eleven meetings across Nimbus, Veda and Orbit; Veda V4 is upcoming so the dashboard shows more than one meeting to prep for.

| # | Date | Account | Title | Attendees | Required facts |
| --- | --- | --- | --- | --- | --- |
| N1 | 2026-03-10 | Nimbus | Discovery | Priya, Meera | Late shipment data breaks weekly reports · about 70 pipelines |
| N2 | 2026-03-24 | Nimbus | Security review | Priya, Arjun, Meera, Deepak | **Deepak: SOC 2 Type II and India data residency are blockers** · Priya promises trust portal access and pen-test summary by Mar 31 |
| N3 | 2026-04-14 | Nimbus | Security follow-up | Priya, Deepak | Deepak confirms trust portal and pen-test summary received · **Deepak: "the trust portal and the pen-test summary were exactly what I needed"** · security sign-off given |
| N4 | 2026-06-02 | Nimbus | Contract and kickoff | Priya, Meera | Signed Enterprise at $62K · Meera offers to be a reference |
| O1 | 2026-05-06 | Orbit | Discovery | Priya, Lakshmi | Stock-level pipelines fail silently · budget "tight this year" |
| O2 | 2026-06-18 | Orbit | Pricing | Priya, Lakshmi, Sameer | **Sameer: DataHawk quoted about 40% lower** · Priya promises a value comparison by Jun 25 |
| O3 | 2026-08-04 | Orbit | Decision | Priya, Lakshmi | Lakshmi confirms value comparison received · **lost to DataHawk on price** · Lakshmi: "reach back out in Q1 if their residency roadmap slips" |
| V1 | 2026-08-20 | Veda | Discovery | Priya, Farah, Nikhil | Patient-analytics pipelines, about 25 · Nikhil wants a sandbox |
| V2 | 2026-09-10 | Veda | Technical review | Priya, Arjun, Farah, Nikhil | **Farah: SOC 2 Type II and patient-data handling are must-haves** · Priya promises sandbox access by Sep 17 |
| V3 | 2026-09-24 | Veda | Sandbox check-in | Priya, Nikhil | Nikhil confirms sandbox access received, likes lineage view · security review set for Oct 1 |
| V4 | 2026-10-01 | Veda | Security deep dive (upcoming) | Priya, Farah, Nikhil | No transcript. Its brief should surface B6: the Nimbus answer to the same objection |

## Live demo meeting

M6 is a short, fixed transcript (about 600–800 words) pasted on stage after the pre-meeting brief is shown. It is written once, reviewed by the team, and never regenerated.

**Must contain:**

- Anita: the budget is now "closer to $75K" because the payments-risk team is joining (triggers B2 contradiction alert).
- Rahul: "we never did get that revised pricing deck"; Priya apologises and promises it by Oct 1 (B1 stays open with a new due date).
- Priya walks Anita through the SOC 2 report and India data residency; Anita: "good, that was my main worry" (closes B5).
- Anita asks how Tracewise compares with DataHawk on price (reinforces B4).
- Rahul says the move went well and Ananya has settled in (closes B3 naturally).
- Next steps: Karan introduces Vikram Rao for procurement by Oct 6; pilot starts Oct 15.

**After logging, the UI must show:** a "learned" toast listing the new budget, 2 new commitments and the updated deck due date; the contradiction alert on the account; and the contact timeline for Anita with today's entries.

**Backup:** Keep a pre-ingested snapshot of the bank after M6 (`make demo-after-m6`) in case provider rate limits hit on stage.

## File format and layout

Seed data lives in `data/seed/` as JSON; the beat sheet is data too, so the validator and golden tests read the same facts the generator used.

```text
data/seed/
├─ company.json            # Tracewise, plans, persona
├─ accounts.json
├─ contacts.json
├─ meetings.json           # all 17: id, account, date, title, attendees, status
├─ beats.json              # required facts per meeting + story beats B1–B6
├─ transcripts/
│  ├─ m1_finedge_discovery.txt
│  ├─ …
│  └─ m6_finedge_live.txt  # hand-reviewed, used on stage
└─ style_refs/             # 3–4 short real-meeting excerpts for tone only
```

**`beats.json` entry:**

```json
{
  "meeting_id": "m4_finedge",
  "required_facts": [
    {"id": "f_deck_promise", "speaker": "c_priya", "text": "Priya promises a revised pricing deck with the pilot option by Sep 3", "must_match": ["pricing deck", "Sep 3|September 3|3rd"], "beat": "B1"}
  ],
  "forbidden": ["75K", "Vikram joined"]
}
```

**Transcript line format** (one utterance per line, per the Technical design):

```text
[2026-08-27T10:02:15+05:30] Priya Nair (Tracewise AE): Thanks for making time, both of you.
[2026-08-27T10:02:21+05:30] Rahul Mehta (VP Engineering, FinEdge): Sure. And thanks for the SOC 2 report, Sneha's happy.
```

## Generation rules for the coding agent

The agent writes a script, `data/scripts/generate.py`, that turns `beats.json` into transcripts through the app's LLM client (`complete_text` for prompt G1, same `LLM_PROVIDER` as the app), one meeting at a time.

1. Generate in date order. Each prompt includes the cast, the meeting's required facts, the previous meetings' one-line summaries, and 1–2 style reference excerpts.
2. Required facts appear once, in natural speech, from the named speaker. Numbers and dates must match exactly.
3. Include realistic texture: greetings, small talk, interruptions, filler ("yeah, so…"), a tangent or two, and a next-steps wrap-up.
4. No facts from later meetings; nothing in the `forbidden` list.
5. Speakers keep their voice from the Contacts table; Karan is sometimes "KS" in Priya's side notes to exercise entity resolution.
6. No target length: minimum 400 spoken words, sanity cap 6,000; 20–40 minutes of timestamps.
7. Temperature about 0.8 for variety; the validator, not the prompt, guarantees correctness.
8. Concurrency: meetings of the same account run in date order; different accounts may run in parallel (up to 4 at once); back off and retry on `429`.
9. M6 is not generated by the script. Draft it once with the same rules, then the team edits it by hand.
10. Generated transcripts are committed to the repo; they are never regenerated at demo time.

## Validation checks

`data/scripts/validate.py` must pass before seeding; a failing transcript is regenerated, not patched by hand (except M6).

- [ ] Every `required_facts[].must_match` pattern is found in its transcript
- [ ] No `forbidden` string appears
- [ ] Every speaker is an attendee of that meeting
- [ ] Timestamps are on the meeting date and increase line by line
- [ ] Word count is within range
- [ ] Every promise except B1's deck is acknowledged in a later meeting of the same account
- [ ] The words "pricing deck" never appear with "received", "got" or "thanks for" before M6

This fixture relies on ingestion marking a ledger commitment `done` when a later transcript acknowledges it; that step is now in the Technical design's ingest flow.

## Optional validation set: AMI Meeting Corpus

AMI is used only to show the memory layer works on real, unscripted meetings; it never enters the demo bank, the dashboard or the golden FinEdge tests.

**Why AMI:** Its scenario meetings are role-played by a four-person design team building a TV remote control prototype over a series of four meetings, so decisions and action items carry across meetings. [source](https://arxiv.org/pdf/2604.17260) Scenario meeting IDs end in a, b, c or d for the first to fourth meeting of a series. [source](https://groups.inf.ed.ac.uk/ami/corpus/meetingids.shtml) Action items are annotated too: 381 across 101 meetings. [source](https://arxiv.org/pdf/2303.16763) The corpus and its annotations are released under CC BY 4.0, so credit the corpus in the README and pitch. [source](https://groups.inf.ed.ac.uk/ami/corpus/license.shtml)

**Why not demo data:** internal design team rather than a sales rep and a prospect, no budget or competitor facts, generic speaker labels instead of names, and long, disfluent transcripts that cost LLM quota.

### Uses

| Use | What to do | Result to report |
| --- | --- | --- |
| Cross-meeting recall test | Ingest one scenario series (a–c) into a separate bank `ami-test`; generate a brief for meeting d | Share of meeting a–c action items that appear in the meeting d brief |
| Extraction accuracy | Run the extractor on 5 annotated meetings; compare commitments with the annotated action items | Precision and recall of action items, e.g. "found 8 of 10" |
| Style reference | Copy 3–4 short excerpts into `data/seed/style_refs/` | None; used only to make generated speech natural |

### Rules

- [ ] Use the manual transcripts and annotations, not audio
- [ ] Map speaker letters to role names ("Project Manager", "Industrial Designer", "UI Designer", "Marketing Expert") before ingest so briefs read naturally
- [ ] Trim each meeting to its first 2,000 words if provider limits bite, and note the trimming in results
- [ ] Keep AMI data under `data/validation/ami/` and the bank `ami-test`; `make reset-demo` never touches it
- [ ] Run as a script (`data/scripts/eval_ami.py`), not in CI, since it uses real Hindsight and LLM provider calls
