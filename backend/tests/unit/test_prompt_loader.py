"""Unit tests for `app.llm.prompt_loader` (prompts live in app/llm/prompts/*.md)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.llm import prompt_loader
from app.llm.prompt_loader import prompt_placeholders, render_prompt

PROMPTS_DIR = Path(prompt_loader.__file__).parent / "prompts"
ALL_PROMPTS = sorted(p.stem for p in PROMPTS_DIR.glob("*.md"))


@pytest.fixture
def tmp_prompts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(prompt_loader, "PROMPTS_DIR", tmp_path)
    return tmp_path


def test_render_with_all_variables(tmp_prompts: Path) -> None:
    (tmp_prompts / "demo.md").write_text("<!-- ID: X -->\nHello {name}, meet {other}.\n")
    assert render_prompt("demo", name="Ann", other="Bo") == "Hello Ann, meet Bo.\n"


def test_missing_variable_raises_keyerror_naming_it(tmp_prompts: Path) -> None:
    (tmp_prompts / "demo.md").write_text("Hello {name}, meet {other}.")
    with pytest.raises(KeyError, match="other"):
        render_prompt("demo", name="Ann")


def test_only_header_comment_line_is_stripped(tmp_prompts: Path) -> None:
    (tmp_prompts / "demo.md").write_text("<!-- header -->\n<!-- not header -->\nbody")
    assert render_prompt("demo") == "<!-- not header -->\nbody"


def test_first_line_kept_when_not_a_comment(tmp_prompts: Path) -> None:
    (tmp_prompts / "demo.md").write_text("first\nsecond")
    assert render_prompt("demo") == "first\nsecond"


def test_escaped_braces_survive(tmp_prompts: Path) -> None:
    (tmp_prompts / "demo.md").write_text('<!-- h -->\nJSON: {{"a": "{v}"}}')
    assert render_prompt("demo", v="1") == 'JSON: {"a": "1"}'


def test_unknown_prompt_raises_clear_error(tmp_prompts: Path) -> None:
    with pytest.raises(FileNotFoundError, match="nope"):
        render_prompt("nope")
    with pytest.raises(FileNotFoundError, match="nope"):
        prompt_placeholders("nope")


def test_placeholders_ignore_escaped_braces(tmp_prompts: Path) -> None:
    (tmp_prompts / "demo.md").write_text('<!-- h -->\n{a} {{"k": 1}} {b} {a}')
    assert prompt_placeholders("demo") == ["a", "b"]


def test_prompts_dir_has_prompts() -> None:
    assert "generate_transcript" in ALL_PROMPTS


@pytest.mark.parametrize("name", ALL_PROMPTS)
def test_every_prompt_renders_with_dummy_values(name: str) -> None:
    placeholders = prompt_placeholders(name)
    rendered = render_prompt(name, **{p: f"<<{p}>>" for p in placeholders})
    assert not rendered.startswith("<!--")
    for p in placeholders:
        assert f"<<{p}>>" in rendered
    # Missing any one placeholder must fail loudly.
    for p in placeholders:
        others = {q: "x" for q in placeholders if q != p}
        with pytest.raises(KeyError):
            render_prompt(name, **others)
