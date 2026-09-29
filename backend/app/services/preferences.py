"""Feedback to style (ticket T19; docs/prompt-specs.md "Preference templates").

Everything here is plain code: no LLM, no Hindsight call on the read path.

- `derive_style_profile(rows)` folds ALL feedback rows (global across accounts and
  briefs) into a `StyleProfile`.
- `apply_style(brief, profile)` is a pure function run at READ time on every brief
  response, so cached briefs adapt with no regeneration. It never touches `length`
  (length only changes a brief when it is generated, via `prompt_style_string`).
- `record_feedback(...)` stores the row first, then retains one template sentence.

Rules: a section's score is a chronological FOLD over its feedback rows (oldest first,
callers pass rows ordered by created_at then id): collapsed -1, down -1, up +1, more +1
(`less` only moves the length), and the running score is clamped to [-2, +3] after every
row. So one `up` or `more` always undoes any number of collapses (-2 -> -1). Score <= -2
hides the section unless it holds a critical item (then it is collapsed instead).
Positive scores sort earlier (higher first); ties keep the default order.
Length: the same kind of fold over more (+1) and less (-1), the running net clamped to
[-3, +3]; net <= -2 short, >= 2 detailed, else standard.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any, Literal, Protocol

from app.core.errors import MemoryUnavailableError
from app.core.time import today
from app.db.brief_repo import SessionFactory
from app.db.feedback_repo import load_all_feedback, store_feedback
from app.memory.memory_service import MemoryService
from app.schemas.api import FeedbackRequest, StyleProfile
from app.schemas.brief import Brief, BriefSection, SectionKey, Severity

logger = logging.getLogger(__name__)

DEFAULT_SECTION_ORDER: list[SectionKey] = list(SectionKey)

SECTION_TITLES: dict[SectionKey, str] = {
    SectionKey.attendees: "Attendees",
    SectionKey.where_left_off: "Where we left off",
    SectionKey.open_commitments: "Open commitments",
    SectionKey.unresolved_objections: "Unresolved objections",
    SectionKey.personal_touchpoints: "Personal touchpoints",
    SectionKey.agenda: "Suggested agenda",
    SectionKey.watch_outs: "Watch-outs",
    SectionKey.alerts: "Alerts",
    SectionKey.your_questions: "Your questions",
}

SCORE_MIN, SCORE_MAX = -2, 3
NET_MIN, NET_MAX = -3, 3
HIDE_THRESHOLD = -2
LENGTH_THRESHOLD = 2
_SCORE = {"collapsed": -1, "down": -1, "up": 1, "more": 1, "less": 0}

_SENTENCES = {
    "collapsed": "On {date} the user collapsed the {title} section of a meeting brief.",
    "up": "On {date} the user found the {title} section useful.",
    "down": "On {date} the user found the {title} section not useful.",
    "more": "On {date} the user asked for more detail in {title}.",
    "less": "On {date} the user asked for less detail in {title}.",
}


class _FeedbackLike(Protocol):
    section: SectionKey
    action: str


def preference_sentence(section: SectionKey, action: str) -> str:
    return _SENTENCES[action].format(date=today().isoformat(), title=SECTION_TITLES[section])


def _scores(rows: Iterable[_FeedbackLike]) -> dict[SectionKey, int]:
    scores = dict.fromkeys(DEFAULT_SECTION_ORDER, 0)
    for row in rows:
        key = SectionKey(row.section)
        scores[key] = max(SCORE_MIN, min(SCORE_MAX, scores[key] + _SCORE.get(row.action, 0)))
    return scores


def _length(rows: Iterable[_FeedbackLike]) -> Literal["short", "standard", "detailed"]:
    net = 0
    for row in rows:
        delta = {"more": 1, "less": -1}.get(row.action, 0)
        net = max(NET_MIN, min(NET_MAX, net + delta))
    if net <= -LENGTH_THRESHOLD:
        return "short"
    if net >= LENGTH_THRESHOLD:
        return "detailed"
    return "standard"


def _titles(keys: Iterable[SectionKey]) -> str:
    return ", ".join(SECTION_TITLES[k] for k in keys)


def derive_style_profile(rows: Iterable[_FeedbackLike]) -> StyleProfile:
    rows = list(rows)
    scores = _scores(rows)
    index = {k: i for i, k in enumerate(DEFAULT_SECTION_ORDER)}
    promoted = sorted((k for k in scores if scores[k] > 0), key=lambda k: (-scores[k], index[k]))
    order = promoted + [k for k in DEFAULT_SECTION_ORDER if k not in promoted]
    hidden = [k for k in DEFAULT_SECTION_ORDER if scores[k] <= HIDE_THRESHOLD]
    length = _length(rows)

    notes: list[str] = []
    if hidden:
        notes.append(f"Hides {_titles(hidden)}.")
    if promoted:
        notes.append(f"Puts {_titles(promoted)} first.")
    if length != "standard":
        notes.append("Prefers shorter briefs." if length == "short" else "Prefers detailed briefs.")
    return StyleProfile(section_order=order, hidden_sections=hidden, length=length, notes=notes)


def prompt_style_string(profile: StyleProfile) -> str:
    """The P3 `{style_profile}` value: length and emphasis only; 'default' if nothing learned."""
    index = {k: i for i, k in enumerate(DEFAULT_SECTION_ORDER)}
    emphasise = [k for i, k in enumerate(profile.section_order) if i < index[k]]
    parts: list[str] = []
    if profile.length != "standard":
        parts.append(f"length: {profile.length}")
    if emphasise:
        parts.append("emphasise: " + ", ".join(k.value for k in emphasise))
    if profile.hidden_sections:
        parts.append("de-emphasise: " + ", ".join(k.value for k in profile.hidden_sections))
    return "; ".join(parts) if parts else "default"


def _has_critical(section: BriefSection) -> bool:
    return any(item.severity == Severity.critical for item in section.items)


def apply_style(brief: Brief, profile: StyleProfile) -> Brief:
    """A new Brief with the profile's order and hiding applied; the input is not mutated.

    A hidden section holding a critical item is collapsed, never dropped. Length is not
    applied here. `preferences_applied` is filled for memory briefs only.
    """
    rank = {k: i for i, k in enumerate(profile.section_order)}
    default_rank = {k: i for i, k in enumerate(DEFAULT_SECTION_ORDER)}
    hidden = set(profile.hidden_sections)

    applied: list[str] = []
    sections: list[BriefSection] = []
    ordered = sorted(brief.sections, key=lambda s: rank.get(s.key, len(rank) + default_rank[s.key]))
    for section in ordered:
        copy = section.model_copy(deep=True)
        if section.key in hidden:
            if _has_critical(section):
                copy.collapsed = True
                applied.append(f"Collapsed {section.title} (it has a critical item)")
            else:
                applied.append(f"Hid {section.title} (repeated negative feedback)")
                continue
        sections.append(copy)

    for key in profile.section_order:
        if key in hidden or rank[key] >= default_rank[key]:
            continue
        title = next((s.title for s in brief.sections if s.key == key), None)
        if title is not None:
            applied.append(f"Moved {title} up")
    if profile.length != "standard":
        word = "shorter" if profile.length == "short" else "more detailed"
        applied.append(f"Prefers {word} briefs (applies when you generate)")

    update: dict[str, Any] = {"sections": sections}
    if brief.mode == "memory":
        update["preferences_applied"] = applied
    return brief.model_copy(update=update, deep=True)


def current_style(session_factory: SessionFactory) -> StyleProfile:
    return derive_style_profile(load_all_feedback(session_factory))


async def record_feedback(
    session_factory: SessionFactory,
    memory: MemoryService,
    brief_id: str,
    request: FeedbackRequest,
) -> StyleProfile:
    """Store the row first, retain one sentence (best effort), return the new profile."""
    store_feedback(session_factory, brief_id, request.section, request.action)
    try:
        await memory.retain_preference(preference_sentence(request.section, request.action))
    except MemoryUnavailableError:
        logger.warning("feedback.retain_failed brief=%s: row kept, memory unavailable", brief_id)
    return current_style(session_factory)
