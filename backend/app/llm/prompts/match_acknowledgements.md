<!-- ID: P2 | output model: AckMatches | temperature: 0 | placeholders: open_commitments, meeting_date, acknowledgements -->
Decide which open commitments were fulfilled, based only on acknowledgements from
a new meeting.

Open commitments (id: text | original words):
{open_commitments}

Acknowledgements from the meeting on {meeting_date} (index: description, quote):
{acknowledgements}

Return {{"closed": [{{"commitment_id": "...", "acknowledgement_index": 0}}]}}.
Rules:
- Only match when the acknowledgement clearly refers to the same deliverable. The
  acknowledgement may use different words than the commitment's text, so also compare it
  with the original words.
- A match requires the acknowledgement to explicitly say the promised item arrived,
  was received, was reviewed or was used.
- A complaint that something was NOT received ("never got it"), or that someone is
  "still waiting" for something, is never a match.
- A commitment that no acknowledgement mentions stays open; do not list it.
- Use only commitment ids from the list above. If nothing matches, return {{"closed": []}}.
