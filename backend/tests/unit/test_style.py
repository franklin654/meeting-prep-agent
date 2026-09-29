"""T19: feedback to style profile, read-time `apply_style`, feedback API. Fakes only."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

import app.main as main_module
from app.api.deps import get_brief_llm, get_memory_service, get_session, get_session_factory
from app.core.errors import MemoryUnavailableError
from app.core.time import today
from app.db import feedback_repo
from app.db.brief_repo import get_fresh_brief
from app.schemas.api import StyleProfile
from app.schemas.brief import (
    Brief,
    BriefItem,
    BriefSection,
    SectionKey,
    Severity,
)
from app.services.brief import SECTION_TITLES
from app.services.preferences import (
    apply_style,
    derive_style_profile,
    preference_sentence,
    prompt_style_string,
)
from tests.fakes.fake_memory_service import FakeMemoryService
from tests.unit.brief_world import (
    M6,
    ScriptedLLM,
    World,
    good_draft,
    make_world,
    queue_objections,
)

SK = SectionKey


class Row(NamedTuple):
    section: SectionKey
    action: str


def rows(*pairs: tuple[SectionKey, str, int]) -> list[Row]:
    return [Row(s, a) for s, a, n in pairs for _ in range(n)]


def _item(i: int, severity: Severity = Severity.info) -> BriefItem:
    return BriefItem(
        id=f"it_{i}", text=f"item {i}", severity=severity, contact_ids=[], citations=[]
    )


def make_brief(mode: str = "memory", critical_in: SectionKey | None = SK.open_commitments) -> Brief:
    present = [
        SK.attendees,
        SK.where_left_off,
        SK.open_commitments,
        SK.personal_touchpoints,
        SK.agenda,
        SK.watch_outs,
    ]
    sections = [
        BriefSection(
            key=key,
            title=SECTION_TITLES[key],
            items=[_item(i, Severity.critical if key == critical_in else Severity.info)],
        )
        for i, key in enumerate(present)
    ]
    return Brief(
        id="br_x",
        meeting_id="m",
        mode=mode,  # type: ignore[arg-type]
        generated_at=datetime(2026, 9, 29, tzinfo=UTC),
        sections=sections,
        facts_used=3,
        preferences_applied=[],
    )


def keys(brief: Brief) -> list[SectionKey]:
    return [s.key for s in brief.sections]


# ---- apply_style / derive ----------------------------------------------------------


def test_default_profile_changes_nothing() -> None:
    brief = make_brief()
    styled = apply_style(brief, derive_style_profile([]))
    assert keys(styled) == keys(brief)
    assert styled.preferences_applied == []
    assert derive_style_profile([]).notes == []
    assert prompt_style_string(derive_style_profile([])) == "default"


def test_hidden_after_two_collapsed_and_undo_by_up() -> None:
    brief = make_brief()
    touch = SK.personal_touchpoints
    one = derive_style_profile(rows((touch, "collapsed", 1)))
    assert touch in keys(apply_style(brief, one))

    two = derive_style_profile(rows((touch, "collapsed", 2)))
    assert two.hidden_sections == [touch]
    styled = apply_style(brief, two)
    assert touch not in keys(styled)
    assert styled.preferences_applied == ["Hid Personal touchpoints (repeated negative feedback)"]

    undone = derive_style_profile(rows((touch, "collapsed", 2), (touch, "up", 1)))
    assert undone.hidden_sections == []
    assert touch in keys(apply_style(brief, undone))
    more = derive_style_profile(rows((touch, "down", 2), (touch, "more", 1)))
    assert more.hidden_sections == []


def test_reorder_by_score_ties_keep_default_order() -> None:
    profile = derive_style_profile(
        rows((SK.watch_outs, "up", 2), (SK.agenda, "up", 1), (SK.where_left_off, "up", 1))
    )
    assert profile.section_order[:3] == [SK.watch_outs, SK.where_left_off, SK.agenda]
    styled = apply_style(make_brief(), profile)
    assert keys(styled) == [
        SK.watch_outs,
        SK.where_left_off,
        SK.agenda,
        SK.attendees,
        SK.open_commitments,
        SK.personal_touchpoints,
    ]
    assert "Moved Watch-outs up" in styled.preferences_applied
    assert profile.notes == ["Puts Watch-outs, Where we left off, Suggested agenda first."]


def test_critical_section_is_collapsed_never_hidden() -> None:
    profile = derive_style_profile(rows((SK.open_commitments, "collapsed", 5)))
    assert SK.open_commitments in profile.hidden_sections
    styled = apply_style(make_brief(), profile)
    section = next(s for s in styled.sections if s.key == SK.open_commitments)
    assert section.collapsed is True
    assert [i.severity for i in section.items] == [Severity.critical]
    assert "Collapsed Open commitments (it has a critical item)" in styled.preferences_applied


def test_no_critical_open_commitments_can_be_hidden() -> None:
    profile = derive_style_profile(rows((SK.open_commitments, "collapsed", 2)))
    styled = apply_style(make_brief(critical_in=None), profile)
    assert SK.open_commitments not in keys(styled)


def test_attendees_can_be_hidden() -> None:
    profile = derive_style_profile(rows((SK.attendees, "collapsed", 2)))
    assert SK.attendees not in keys(apply_style(make_brief(), profile))


def test_no_memory_gets_style_but_no_preferences_applied() -> None:
    profile = derive_style_profile(
        rows((SK.personal_touchpoints, "collapsed", 2), (SK.watch_outs, "up", 1))
    )
    styled = apply_style(make_brief(mode="no_memory"), profile)
    assert SK.personal_touchpoints not in keys(styled)
    assert keys(styled)[0] == SK.watch_outs
    assert styled.preferences_applied == []


def test_apply_style_is_pure() -> None:
    brief = make_brief()
    before = brief.model_dump()
    profile = derive_style_profile(
        rows(
            (SK.open_commitments, "collapsed", 3),
            (SK.agenda, "collapsed", 2),
            (SK.watch_outs, "up", 1),
        )
    )
    styled = apply_style(brief, profile)
    assert brief.model_dump() == before
    assert styled is not brief
    styled.sections[0].items[0].text = "changed"
    assert brief.model_dump() == before


def test_style_keeps_facts_used_and_items_of_visible_sections() -> None:
    profile = derive_style_profile(
        rows((SK.agenda, "collapsed", 2), (SK.open_commitments, "up", 1))
    )
    styled = apply_style(make_brief(), profile)
    assert styled.facts_used == 3
    commitments = next(s for s in styled.sections if s.key == SK.open_commitments)
    assert commitments.collapsed is False and len(commitments.items) == 1


def test_length_rule_and_notes() -> None:
    assert derive_style_profile(rows((SK.agenda, "less", 1))).length == "standard"
    short = derive_style_profile(rows((SK.agenda, "less", 1), (SK.alerts, "less", 1)))
    assert short.length == "short"
    assert derive_style_profile(rows((SK.agenda, "more", 2))).length == "detailed"
    mixed = derive_style_profile(rows((SK.agenda, "more", 3), (SK.alerts, "less", 2)))
    assert mixed.length == "standard"
    profile = derive_style_profile(
        rows((SK.personal_touchpoints, "collapsed", 2), (SK.agenda, "less", 2))
    )
    assert profile.notes == ["Hides Personal touchpoints.", "Prefers shorter briefs."]
    assert prompt_style_string(profile) == "length: short; de-emphasise: personal_touchpoints"
    # length is never applied at read time; only noted
    styled = apply_style(make_brief(), profile)
    assert "Prefers shorter briefs (applies when you generate)" in styled.preferences_applied
    assert len(styled.sections[0].items) == 1


def test_prompt_style_string_emphasis() -> None:
    profile = derive_style_profile(rows((SK.watch_outs, "up", 1), (SK.agenda, "less", 2)))
    assert prompt_style_string(profile) == "length: short; emphasise: watch_outs"


def test_preference_sentences() -> None:
    pre = f"On {today().isoformat()} the user"
    assert (
        preference_sentence(SK.personal_touchpoints, "collapsed")
        == f"{pre} collapsed the Personal touchpoints section of a meeting brief."
    )
    assert preference_sentence(SK.watch_outs, "up") == f"{pre} found the Watch-outs section useful."
    assert (
        preference_sentence(SK.watch_outs, "down")
        == f"{pre} found the Watch-outs section not useful."
    )
    assert (
        preference_sentence(SK.agenda, "more")
        == f"{pre} asked for more detail in Suggested agenda."
    )
    assert (
        preference_sentence(SK.agenda, "less")
        == f"{pre} asked for less detail in Suggested agenda."
    )


# ---- API ---------------------------------------------------------------------------


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    yield from make_world(tmp_path)


@pytest.fixture
def llm() -> ScriptedLLM:
    return ScriptedLLM(good_draft)


@pytest.fixture
def client(world: World, llm: ScriptedLLM) -> Iterator[TestClient]:
    def _session() -> Iterator[Session]:
        with Session(world.engine) as s:
            yield s

    overrides = main_module.app.dependency_overrides
    overrides[get_session] = _session
    overrides[get_session_factory] = lambda: world.session_factory
    overrides[get_brief_llm] = lambda: llm
    overrides[get_memory_service] = lambda: world.memory
    yield TestClient(main_module.app)
    overrides.clear()


def _post_brief(client: TestClient, meeting: str = M6, mode: str = "memory") -> Brief:
    if mode == "memory":
        queue_objections(main_module.app.dependency_overrides[get_memory_service]())  # type: ignore[arg-type]
    response = client.post(f"/api/meetings/{meeting}/brief?mode={mode}")
    assert response.status_code == 200, response.text
    return Brief.model_validate(response.json())


def _feedback(client: TestClient, brief_id: str, section: str, action: str) -> Any:
    return client.post(
        f"/api/briefs/{brief_id}/feedback", json={"section": section, "action": action}
    )


def _preferences(memory: FakeMemoryService) -> list[str]:
    return [i.text for i in memory.items if "kind:preference" in i.tags]


def test_feedback_stores_row_and_retains_one_sentence(client: TestClient, world: World) -> None:
    brief = _post_brief(client)
    response = _feedback(client, brief.id, "personal_touchpoints", "collapsed")
    assert response.status_code == 200
    profile = StyleProfile.model_validate(response.json())
    assert profile.hidden_sections == []
    with world.session_factory() as session:
        stored = feedback_repo.list_all_feedback(session)
    assert [(f.brief_id, f.section, f.action) for f in stored] == [
        (brief.id, SK.personal_touchpoints, "collapsed")
    ]
    assert stored[0].id.startswith("fb_")
    assert _preferences(world.memory) == [
        f"On {today().isoformat()} the user collapsed the Personal touchpoints section "
        "of a meeting brief."
    ]


def test_unknown_brief_is_404_and_stores_nothing(client: TestClient, world: World) -> None:
    response = _feedback(client, "br_nope", "agenda", "up")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert _preferences(world.memory) == []
    with world.session_factory() as session:
        assert feedback_repo.list_all_feedback(session) == []


def test_retain_failure_keeps_row_and_returns_200(
    client: TestClient, world: World, caplog: pytest.LogCaptureFixture
) -> None:
    brief = _post_brief(client)

    async def boom(sentence: str) -> None:
        raise MemoryUnavailableError("down")

    world.memory.retain_preference = boom  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING):
        response = _feedback(client, brief.id, "agenda", "collapsed")
    assert response.status_code == 200
    with world.session_factory() as session:
        assert len(feedback_repo.list_all_feedback(session)) == 1
    assert "feedback.retain_failed" in caplog.text
    assert "collapsed the" not in caplog.text


@pytest.mark.parametrize(
    "body",
    [
        {"section": "nonsense", "action": "up"},
        {"section": "agenda", "action": "sideways"},
        {"section": "agenda"},
    ],
)
def test_feedback_validation_422(client: TestClient, body: dict[str, str]) -> None:
    brief = _post_brief(client)
    assert client.post(f"/api/briefs/{brief.id}/feedback", json=body).status_code == 422


def test_get_style_reflects_rows(client: TestClient) -> None:
    assert client.get("/api/style").json() == {
        "section_order": [k.value for k in SectionKey],
        "hidden_sections": [],
        "length": "standard",
        "notes": [],
    }
    brief = _post_brief(client)
    for _ in range(2):
        _feedback(client, brief.id, "personal_touchpoints", "collapsed")
        _feedback(client, brief.id, "agenda", "less")
    style = client.get("/api/style").json()
    assert style["hidden_sections"] == ["personal_touchpoints"]
    assert style["length"] == "short"
    assert style["notes"] == ["Hides Personal touchpoints.", "Prefers shorter briefs."]


def test_briefs_come_back_styled_and_record_stays_unstyled(
    client: TestClient, world: World
) -> None:
    brief = _post_brief(client)
    assert SK.personal_touchpoints in keys(brief)
    for _ in range(2):
        _feedback(client, brief.id, "personal_touchpoints", "collapsed")
    _feedback(client, brief.id, "watch_outs", "up")

    got = Brief.model_validate(client.get(f"/api/meetings/{M6}/brief").json())
    assert SK.personal_touchpoints not in keys(got)
    assert keys(got)[0] == SK.watch_outs
    assert got.preferences_applied

    regenerated = _post_brief(client)
    assert regenerated.id == brief.id
    assert SK.personal_touchpoints not in keys(regenerated)
    assert keys(regenerated)[0] == SK.watch_outs

    stored = get_fresh_brief(world.session_factory, M6, "memory")
    assert stored is not None
    assert keys(stored) == [k for k in SectionKey if k in keys(brief)]
    assert stored.preferences_applied == []
    assert all(not s.collapsed for s in stored.sections)


def test_pricing_deck_survives_hiding_open_commitments(client: TestClient) -> None:
    brief = _post_brief(client)
    for _ in range(5):
        _feedback(client, brief.id, "open_commitments", "collapsed")
    got = Brief.model_validate(client.get(f"/api/meetings/{M6}/brief").json())
    section = next(s for s in got.sections if s.key == SK.open_commitments)
    assert section.collapsed is True
    assert any("pricing deck" in i.text.lower() for i in section.items)
    assert any(i.severity == Severity.critical for i in section.items)


def test_no_memory_response_styled_without_preferences(client: TestClient) -> None:
    memory_brief = _post_brief(client)
    no_memory = _post_brief(client, mode="no_memory")
    for _ in range(2):
        _feedback(client, memory_brief.id, "personal_touchpoints", "collapsed")
    got = Brief.model_validate(client.get(f"/api/meetings/{M6}/brief?mode=no_memory").json())
    assert got.id == no_memory.id
    assert got.preferences_applied == []
    assert SK.personal_touchpoints not in keys(got)


def test_feedback_applies_to_other_meetings_cached_brief_without_llm(
    client: TestClient, llm: ScriptedLLM
) -> None:
    m6 = _post_brief(client)
    other = _post_brief(client, meeting="m5_finedge")
    assert SK.personal_touchpoints in keys(other)
    for _ in range(2):
        _feedback(client, m6.id, "personal_touchpoints", "collapsed")
    calls = len(llm.calls)
    got = Brief.model_validate(client.get("/api/meetings/m5_finedge/brief").json())
    assert SK.personal_touchpoints not in keys(got)
    assert len(llm.calls) == calls


def test_generate_passes_length_and_emphasis_to_p3(client: TestClient, llm: ScriptedLLM) -> None:
    brief = _post_brief(client)
    assert "User's brief style: default" in llm.calls[-1].prompt
    for _ in range(2):
        _feedback(client, brief.id, "agenda", "less")
        _feedback(client, brief.id, "personal_touchpoints", "collapsed")
    _feedback(client, brief.id, "watch_outs", "up")
    _post_brief(client)
    assert (
        "User's brief style: length: short; emphasise: watch_outs; "
        "de-emphasise: personal_touchpoints" in llm.calls[-1].prompt
    )


def test_undo_after_many_collapses_is_one_up_or_more() -> None:
    touch = SK.personal_touchpoints
    assert derive_style_profile(rows((touch, "collapsed", 2))).hidden_sections == [touch]
    assert derive_style_profile(rows((touch, "collapsed", 5))).hidden_sections == [touch]
    for action in ("up", "more"):
        undone = derive_style_profile(rows((touch, "collapsed", 5), (touch, action, 1)))
        assert undone.hidden_sections == []


def test_score_fold_is_chronological() -> None:
    touch = SK.personal_touchpoints
    seq = [Row(touch, "collapsed"), Row(touch, "up"), Row(touch, "collapsed")]
    assert derive_style_profile(seq).hidden_sections == []
    seq = [Row(touch, "up"), Row(touch, "collapsed"), Row(touch, "collapsed")]
    assert derive_style_profile(seq).hidden_sections == []
    seq = [Row(touch, "collapsed"), Row(touch, "collapsed"), Row(touch, "up"), Row(touch, "down")]
    assert derive_style_profile(seq).hidden_sections == [touch]


def test_score_ceiling_caps_ordering_growth() -> None:
    # 10 ups clamp to +3, so 3 ups on agenda tie it and default order decides.
    profile = derive_style_profile(rows((SK.watch_outs, "up", 10), (SK.agenda, "up", 3)))
    assert profile.section_order[:2] == [SK.agenda, SK.watch_outs]
    # after two downs the clamped section sits at +1, below a fresh two-up section
    profile = derive_style_profile(
        rows((SK.watch_outs, "up", 10), (SK.watch_outs, "down", 2), (SK.agenda, "up", 2))
    )
    assert profile.section_order[:2] == [SK.agenda, SK.watch_outs]


def test_length_net_is_clamped() -> None:
    lots_less = rows((SK.agenda, "less", 8))
    assert derive_style_profile(lots_less).length == "short"
    assert derive_style_profile(lots_less + rows((SK.agenda, "more", 1))).length == "short"
    assert derive_style_profile(lots_less + rows((SK.agenda, "more", 2))).length == "standard"
    lots_more = rows((SK.agenda, "more", 8))
    assert derive_style_profile(lots_more + rows((SK.agenda, "less", 2))).length == "standard"
