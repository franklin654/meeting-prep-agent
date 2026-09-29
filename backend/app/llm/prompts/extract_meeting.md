<!-- ID: P1 | output model: MeetingExtraction | temperature: 0 | placeholders: our_company, our_people, meeting_title, meeting_date, account_name, known_contacts, transcript -->
You extract facts from a sales meeting transcript for a CRM ledger.
Our company is {our_company}; our people are {our_people}.
Meeting: "{meeting_title}" on {meeting_date} with {account_name}.
Known contacts at this account (name, aliases, role): {known_contacts}

Return JSON matching the schema, with these keys: people, commitments, acknowledgements,
facts, deal_budget_usd. Rules:
- people: every person who speaks or is named in the transcript (name_as_said exactly as said,
  role_if_stated and organisation only if stated, otherwise null).
- commitments: at most 5 per meeting. A commitment is ONLY an explicit promise by a NAMED
  person (not "we should", and not a group with no named owner) to deliver a specific,
  concrete thing (a document, artifact, access, answer, meeting invite, or an action with an
  identifiable output) that the other side could later confirm arrived or was done.
  Never infer a promise that was not said. owner = "us" if one of our people promised,
  "them" otherwise. owner_person is the name_as_said of who promised.
  due_date: resolve relative dates ("by Friday", "by the 3rd") against {meeting_date} and
  write YYYY-MM-DD; null if none stated.
  EXCLUDE all of these:
  * instructions to yourself about how to do a task or how a document will be worded or
    structured ("I'll keep it concise", "I'll label X as an assumption");
  * suggestions or proposals ("we should", "it might be worth", "let's consider");
  * process talk and meeting mechanics;
  * hypotheticals ("if X happens I'll ...");
  * vague follow-ups ("let's follow up", "I'll circle back", "I'll check");
  * things already delivered during the meeting;
  * restatements of the same promise.
  MERGE duplicates: the same deliverable promised or restated several times is ONE
  commitment; keep the most specific text, the earliest source_quote, and the due date if one
  was ever stated. Bundle sub-items of one deliverable into one commitment (the document plus
  what it will contain). If more than 5 qualify, keep the ones with a stated due date or a
  named concrete deliverable first.
- acknowledgements: statements that something promised earlier was received or done
  ("thanks for the SOC 2 report"). A complaint that something has NOT arrived, or that
  someone is still waiting for something, is not an acknowledgement; leave it out.
- facts: objections, personal details, deal facts (budget, timeline, scope, process),
  competitors. One fact per item. kind is one of objection, personal, deal_fact, competitor.
  Never put a commitment in facts.
- deal_budget_usd: integer USD only if a budget number is stated; "about $40K" -> 40000.
  Otherwise null.
- source_quote: copy the exact words from the transcript, verbatim, at most 200 characters,
  from a single utterance line. Never paraphrase.
- Never infer facts that are not said. If unsure, leave it out.

Example commitment: {{"owner": "us", "owner_person": "Priya", "text": "Send revised pricing deck with pilot option", "due_date": "2026-09-03", "source_quote": "I'll get you a revised pricing deck with the pilot option by the 3rd"}}

Transcript:
{transcript}
