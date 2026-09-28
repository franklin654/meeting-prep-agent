<!-- ID: G1 | output model: none (plain-text transcript via complete_text) | temperature: 0.8 -->
Write a realistic transcript of a sales meeting.
Date: {date}. Title: {title}. Duration about {minutes} minutes.
Participants and voices: {cast}
Story so far: {previous_summaries}
Style examples of natural speech (tone only, do not copy content): {style_refs}

The transcript MUST include each of these facts once, said naturally by the named
speaker, with numbers and dates exactly as given:
{required_facts}
It must NOT mention: {forbidden}

Format: one utterance per line:
[{date}T<hh:mm:ss>+05:30] <Full Name> (<Role>, <Company>): <words>
Include greetings, small talk, filler words, interruptions, one tangent, and a
next-steps wrap-up. {min_words}-{max_words} words.
