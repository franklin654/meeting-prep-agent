"""Loads and renders prompt files from `app/llm/prompts/*.md`.

Each prompt file may start with a single `<!-- ... -->` header line (id, output
model, placeholders); it is stripped before rendering. The body is a
`str.format` template, so literal braces (e.g. JSON examples) are written
`{{` and `}}`.
"""

from __future__ import annotations

import string
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def _load_body(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Unknown prompt {name!r}: no file {path}")
    text = path.read_text(encoding="utf-8")
    first, sep, rest = text.partition("\n")
    if first.startswith("<!--"):
        return rest if sep else ""
    return text


def prompt_placeholders(name: str) -> list[str]:
    """Placeholder names used in the prompt body, in first-appearance order."""
    seen: list[str] = []
    for _, field, _, _ in string.Formatter().parse(_load_body(name)):
        if field is not None and field != "" and field not in seen:
            seen.append(field)
    return seen


def render_prompt(name: str, /, **variables: str) -> str:
    """Render prompt `name`; raises `KeyError` naming any missing placeholder."""
    body = _load_body(name)
    try:
        return body.format(**variables)
    except KeyError as exc:
        raise KeyError(
            f"Prompt {name!r} is missing a value for placeholder {exc.args[0]!r}"
        ) from exc
