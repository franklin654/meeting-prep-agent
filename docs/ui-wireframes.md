# UI wireframes: source of truth for the UI overhaul

Source: the design canvas "Meeting Prep Agent – UI/UX Wireframes" (six boards, 1280x800 each: Today, Meeting brief, Contact memory, Ask, Post-meeting capture, Memory inspector). This file is the text version of those boards so a coding agent can build from it.

Names and numbers in the wireframes are placeholders (Priya Raman at FinEdge, Marcus Lee at Northwind, Sofia Alvarez at Helio, the user "Aarav"). The app uses the seeded data instead: the AE is Priya Nair at Tracewise, and FinEdge's contacts are Anita Desai, Karan Shah, Rahul Mehta and Sneha Iyer. The AE name and company come from data/seed/company.json, never from DEMO_USER_ID.

The numbered orange pins and the yellow legend strip at the bottom of each board are documentation. Do not build them.

## 1. Design tokens

Fonts: IBM Plex Sans (400, 600) for text; IBM Plex Mono (500) for small uppercase section labels (11px, letter-spacing 0.08em). Bundle them locally (for example @fontsource packages) so the app works offline.

Colours:
- Page background #F7F5F0. Sidebar background #EFECE5. Card background #FFFFFF.
- Borders #D6D2C8 (stronger #B8B3A6). Hover fill #E6E2D9. Placeholder bars #E4E1DA.
- Text #1F2328. Muted text #4A4F57.
- Memory accent (teal): #0F6E7A, hover #0A4F58, text #0B5B66, tint background #E6F2F3. Use it for everything that comes from memory: source chips, memory chips, the active tab underline, the 2px border of the "hero" card, the logo mark.
- Warning and overdue (amber): text #8A4105, border #9A4A06, tint #FBEFE0.
- Red is reserved for the single critical item (keep the app's existing critical red).
- Primary button: fill #1F2328, hover #3A3F47, white text. Ghost button: white, dark border.

Shape: cards have a 10px radius, a 1px border and 16px padding. Chips are fully rounded, 12px text. Buttons, inputs and tabs are at least 44px tall. Inputs have an 8px radius. The "source chip" is mono 11px, teal text on the teal tint, 4px radius, and shows meeting title and date (never a raw id). Section labels use the mono uppercase style.

The current build uses an indigo accent. Replace it with the teal token, defined in one place. Do not change the meaning of red and amber.

## 2. Shell (all screens)

- Left sidebar, 216px wide: logo mark plus "Prep Agent", then nav items with icons: Today, Contacts, Ask, Capture, Memory. The active item is white with a border and bold text. At the bottom: "Signed in as <AE name> · <company>".
- Top bar, 64px: page title on the left; page actions on the right.
- Body: 22px 28px padding, two columns where a right rail exists.
- Below 1024px wide the sidebar collapses to a top bar. Every screen needs loading, empty and error states.

## 3. Screens

### 3.1 Today

Purpose: the next meeting is the hero card and its brief is ready before you ask.

Top bar: title "Today"; a search box ("Search contacts or meetings"); a ghost button "Add meeting notes" (goes to Capture). Add a primary "Schedule meeting" button (the wireframe lacks it; the product needs it).

Main column: label "Upcoming meetings" and a date chip. One card per meeting: time, contact name and role, company, meeting title; chips: "Brief ready" (teal), "N open follow-ups" (amber when any), "N past meetings"; buttons "Open brief" (or "Generate brief" when none) and "Log notes". The first upcoming card has the 2px teal border. A meeting with no history shows a "No history yet" chip and a "Generic brief" note.

Right rail: card "Needs your attention" (overdue promises we owe, promises they owe that are late, meetings with no memory yet, "Brief ready"), card "How I prep for you" (learned style rules such as "Short briefs", "Hidden: Personal touchpoints", with a link to change them on the Memory screen).

### 3.2 Meeting brief

Header: breadcrumb "Today / <account>"; title "Brief for <contact>, <time>"; buttons "Regenerate" (ghost) and "Mark as prepared" (primary). Keep the existing memory toggle (With memory / Without / Side by side), the "N facts used" and "N preferences applied" chips, and the "Needs attention" block.

Main column, in order:
1. Where we left off: short text plus source chips.
2. You owe them: ledger items we promised, each with title, date promised, status chip (overdue = amber, or the one critical item; open = neutral) and a source chip.
3. They owe you: same shape for promises made by the customer.
4. Objections to expect: ranked by how often raised, for example "Data residency for EU customers · raised twice · 12 Aug, 27 Jul"; each date is a source chip.
5. Suggested plan for the call: a numbered list of talking points.
Also keep the existing Personal touchpoints, Watch-outs, deal snapshot and cross-contact alert.

Right rail:
- Contact card per attendee: name, role, company, "Style:" line (short learned communication preferences with source chips), "Recent meetings" list (date, title, link), open follow-up count.
- "Memory used" card: "N facts from M meetings", with links "Ask about <name>" and "Full history".

### 3.3 Contacts and Contact memory

Left: "Contacts" list with a search box; each row shows name, role and company. Right: the selected contact.

Header: name, role and company; chips "N meetings", "N open follow-ups". Tabs: Timeline | Facts | Follow-ups | Preferences (active tab has the teal underline).
- Timeline: grouped by meeting date and title; each stored item shows a kind chip and the text.
- Facts: all typed facts, filterable by kind.
- Follow-ups: ledger commitments for that contact with status; edit due date, mark done, delete.
- Preferences: personal and communication-preference facts.
Cards: "What I have learned" (2 to 4 cross-meeting patterns, each linking to its meeting; a "Refresh" button; hide the card when there are none) and "You stay in control" (buttons "Edit memory" and "Add note"; the user can correct, hide or add).

### 3.4 Ask (memory Q&A)

Header chip "Scope: <contact>, <account>" with "Change scope" (account, contact or meeting). Thread of You and Agent messages; agent answers carry source chips. Suggested-question chips ("What did I promise her?", "Who else is involved?", "Summarize objections"). Input "Ask anything about <name>" and a Send button.

Right rail: "Sources for this answer" (date plus quote for each citation of the selected answer) and a "Not found in memory" callout: when nothing is stored the agent says so ("Nothing in memory covers that yet.") and offers to capture the answer after the call. Answers are scoped, so context never leaks across accounts.

### 3.5 Capture (post-meeting)

Title "Capture notes", subtitle "Takes under a minute after each call". Stepper: 1 Paste, 2 Review, 3 Saved.
- Paste: meeting selector (upcoming and recent meetings), a large notes/transcript textarea, a hint that files can be uploaded, and the button "Extract memories".
- Review: a list of what was found, each with a checkbox and a kind chip: commitment, objection, personal, deal fact, competitor, "closes" (closes an open follow-up; names it) and "duplicate" (merges into an existing memory; unchecked by default). Summary line, for example "3 new, 1 closes a follow-up, 1 merged". Buttons: "Discard" and "Save to memory".
- Saved: progress, then a summary of what was learned, with links to the brief and the contact.
Voice notes are not part of the build.

### 3.6 Memory inspector

Title "Memory inspector: how the agent improves with every meeting". Contents: the "Memory on / Memory off" toggle (generic baseline versus memory), "Personalization over time" (the wireframe's interaction 1 / 5 / 20 cards are marked "Illustrative demo view"; the real build shows real numbers instead: facts known after each meeting), and "Memory bank" (facts stored per contact, counted by kind). A "Try it live" panel with "Open a brief". Do not ship invented numbers.

## 4. Vocabulary

The app's fact kinds are: commitment, objection, personal, deal_fact, competitor. The wireframe's kinds map as follows and no new kinds are added: preference and context show as "Personal" (communication preferences are personal facts); decision shows as "Deal fact".

## 5. Gap list (build as of the end of Phase 5)

Built: meetings list with digest, briefs with citations and the memory toggle, contact timeline, Ask drawer, notes logging for existing meetings, rule-based style learning, nudges.

Missing and to be built: sidebar shell and teal tokens; scheduling meetings; creating accounts and contacts; capture review before saving; Contacts list and search; contact tabs, edits and hiding; learned patterns; You owe / They owe lists; ranked objections; contact cards and the "Memory used" panel in briefs; "Mark as prepared"; first-meeting brief; full Ask page with scope switching and a sources panel; Memory inspector; the "How I prep for you" panel; search on Today.
