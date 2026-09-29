Derive up to four durable, useful patterns about this sales contact from the supplied, quote-verified facts.

Contact: {{ contact_name }} ({{ contact_role }}) at {{ account_name }}.

Rules:
- Use only the facts below. Do not infer personality or intent beyond their wording.
- Each pattern must cite one or more exact fact ids from the input.
- Prefer recurring preferences, decision criteria, or stable working patterns over one-off events.
- Return an empty patterns list when no useful pattern is supported.

Facts:
{{ facts }}
