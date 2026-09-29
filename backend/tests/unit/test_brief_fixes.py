"""T14c: critical cap, competitor query from the persona, timing log, concurrent upsert,
empty briefs, mental-model citation. Fakes only, no network."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterator, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

import app.main as main_module
from app.db.brief_repo import new_brief_stamp, save_brief
from app.db.models import BriefRecord, Commitment, Meeting, MeetingAttendee
from app.db.session import BRIEF_UNIQUE_INDEX, create_db_and_tables, ensure_brief_unique_index
from app.memory.tags import account_tag, fact_kind_tag, meeting_tag
from app.schemas.brief import Brief, BriefDraft, SectionKey, Severity
from app.schemas.enums import CommitmentStatus, FactKind, Owner
from app.schemas.memory import MemoryHit
from app.services import brief as brief_module
from app.services.brief import (
    COMPETITOR_QUERY,
    _competitor_names,
    competitor_query,
    load_persona,
)
from tests.unit.brief_world import (
    ACC,
    DECK_QUOTE,
    M6,
    ScriptedLLM,
    World,
    evidence_ids,
    item,
    make_world,
)
from tests.unit.test_api_briefs import _install
from tests.unit.test_brief_service import make, section


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    yield from make_world(tmp_path)


def add_commitments(world: World, rows: list[Commitment]) -> None:
    with Session(world.engine) as s:
        for row in rows:
            s.add(row)
        s.commit()


def overdue_row(cid: str, owner: Owner, due: date, text: str | None = None) -> Commitment:
    return Commitment(
        id=cid,
        account_id=ACC,
        meeting_id="m3_finedge",
        owner=owner,
        text=text or f"Overdue promise {cid}",
        due_date=due,
        status=CommitmentStatus.open,
        source_quote=f"quote {cid}",
    )


def critical_items(brief: Brief) -> list[tuple[SectionKey, str]]:
    return [
        (s.key, i.id) for s in brief.sections for i in s.items if i.severity == Severity.critical
    ]


# ---- 1. critical cap -----------------------------------------------------------------------


async def test_at_most_one_critical_item_and_group_remaining_overdue(world: World) -> None:
    rows = [overdue_row(f"cm_us{i}", Owner.us, date(2026, 9, 4 + i)) for i in range(6)]
    rows += [overdue_row(f"cm_them{i}", Owner.them, date(2026, 8, 10 + i)) for i in range(7)]
    add_commitments(world, rows)  # 14 overdue with cm_deck; the customer's are the oldest

    def draft(prompt: str) -> BriefDraft:
        ledger = evidence_ids(prompt, "OVERDUE")
        return BriefDraft(
            sections={
                SectionKey.agenda: [item("Clear the overdue items", ledger[:2], Severity.critical)],
                SectionKey.alerts: [
                    item("Overdue promises pile up", ledger[2:4], Severity.critical)
                ],
                SectionKey.watch_outs: [
                    item("DataHawk is cheaper", evidence_ids(prompt, "DataHawk"), Severity.critical)
                ],
            }
        )

    brief, _ = await make(world, draft)

    # The most overdue us-owned commitment stays red; all other us-owned rows are grouped.
    assert [k for k, _ in critical_items(brief)] == [SectionKey.open_commitments]
    commitments = section(brief, SectionKey.open_commitments)
    assert len(commitments) == 9  # critical, grouped us-owned, and individual customer rows
    assert "pricing deck" in commitments[0].text
    assert commitments[0].severity == Severity.critical
    grouped = next(i for i in commitments if i.text.startswith("Also overdue:"))
    assert grouped.severity == Severity.warning
    assert "cm_us0" in grouped.text
    # Customer-owned overdue rows are informational even though they are older.
    them = [i for i in commitments if "cm_them" in i.text]
    assert len(them) == 7 and all(i.severity == Severity.info for i in them)
    # Restating overdue rows in other sections is never critical.
    assert all(i.severity == Severity.warning for i in section(brief, SectionKey.agenda))
    assert section(brief, SectionKey.alerts) == []
    assert all(i.severity == Severity.warning for i in section(brief, SectionKey.watch_outs))
    # The deck is still cited to its source meeting with the real quote.
    (citation,) = commitments[0].citations
    assert citation.meeting_id == "m4_finedge" and citation.quote == DECK_QUOTE


async def test_customer_owned_overdue_items_are_never_critical(world: World) -> None:
    add_commitments(
        world,
        [
            overdue_row("cm_them_a", Owner.them, date(2026, 8, 1)),
            overdue_row("cm_them_b", Owner.them, date(2026, 8, 2)),
        ],
    )

    brief, _ = await make(world)  # deck is the only us-owned overdue row

    commitments = section(brief, SectionKey.open_commitments)
    assert len(commitments) == 3
    assert [i.severity for i in commitments] == [
        Severity.critical,
        Severity.info,
        Severity.info,
    ]
    assert "pricing deck" in commitments[0].text  # us-owned outranks the older customer rows
    assert len(critical_items(brief)) == 1


async def test_zero_us_owned_overdue_means_zero_critical(world: World) -> None:
    with Session(world.engine) as s:
        s.delete(s.get(Commitment, "cm_deck"))
        s.commit()
    add_commitments(
        world,
        [
            overdue_row("cm_them_a", Owner.them, date(2026, 8, 1)),
            overdue_row("cm_them_b", Owner.them, date(2026, 8, 2)),
        ],
    )

    def shouting(prompt: str) -> BriefDraft:
        return BriefDraft(
            sections={
                SectionKey.open_commitments: [
                    item("Their promise", evidence_ids(prompt, "cm_them_a"), Severity.critical)
                ]
            }
        )

    brief, _ = await make(world, shouting)

    assert critical_items(brief) == []
    assert len(section(brief, SectionKey.open_commitments)) == 2


async def test_critical_cap_with_fewer_than_two_candidates(world: World) -> None:
    brief, _ = await make(world)  # only the deck is overdue

    assert len(critical_items(brief)) == 1
    assert section(brief, SectionKey.open_commitments)[0].severity == Severity.critical


async def test_no_overdue_means_nothing_critical_even_if_llm_says_so(world: World) -> None:
    with Session(world.engine) as s:
        deck = s.get(Commitment, "cm_deck")
        assert deck is not None
        deck.due_date = date(2026, 10, 1)
        s.add(deck)
        s.commit()

    def shouting(prompt: str) -> BriefDraft:
        return BriefDraft(
            sections={
                SectionKey.agenda: [
                    item("Urgent!", evidence_ids(prompt, "DataHawk"), Severity.critical)
                ]
            }
        )

    brief, _ = await make(world, shouting)

    assert critical_items(brief) == []


# ---- 2. competitor query from the persona --------------------------------------------------


@pytest.fixture
def persona_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    def write(competitor: Any) -> None:
        data: dict[str, Any] = {"ae": {"name": "Priya Nair"}, "vendor": {"name": "Tracewise"}}
        if competitor is not None:
            data["competitor"] = competitor
        path = tmp_path / "company.json"
        path.write_text(json.dumps(data))
        monkeypatch.setattr(brief_module, "_COMPANY_JSON", path)
        load_persona.cache_clear()

    yield write
    load_persona.cache_clear()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Zorblax", ["Zorblax"]),
        ({"name": "Zorblax", "fictional": True}, ["Zorblax"]),
        (["Zorblax", {"name": "Quuxco"}, "Zorblax", {"nope": 1}, " "], ["Zorblax", "Quuxco"]),
        (None, []),
        ("", []),
    ],
)
def test_competitor_names_accepts_string_object_or_list(raw: Any, expected: list[str]) -> None:
    assert _competitor_names(raw) == expected


def test_competitor_query_wording() -> None:
    assert competitor_query([]) == COMPETITOR_QUERY
    assert competitor_query(["Zorblax", "Quuxco"]) == f"{COMPETITOR_QUERY} such as Zorblax, Quuxco"


def log_recalls(world: World, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, FactKind | None]]:
    calls: list[tuple[str, FactKind | None]] = []
    original = world.memory.recall_facts

    async def logged(
        *, query: str, tags: Sequence[str], fact_kind: FactKind | None = None
    ) -> list[MemoryHit]:
        if tuple(tags) == (account_tag(ACC),):
            calls.append((query, fact_kind))
        return await original(query=query, tags=tags, fact_kind=fact_kind)

    monkeypatch.setattr(world.memory, "recall_facts", logged)
    return calls


async def test_watch_out_queries_carry_configured_competitor_names(
    world: World, monkeypatch: pytest.MonkeyPatch, persona_file: Any
) -> None:
    persona_file("Zorblax")
    world.memory.items = [i for i in world.memory.items if i.memory_id != "w_datahawk"]  # empty
    calls = log_recalls(world, monkeypatch)

    await make(world, lambda p: BriefDraft(sections={}))

    expected = f"{COMPETITOR_QUERY} such as Zorblax"
    assert calls == [(expected, FactKind.competitor), (expected, None)]  # fallback has it too


async def test_no_competitor_in_persona_keeps_the_generic_query(
    world: World, monkeypatch: pytest.MonkeyPatch, persona_file: Any
) -> None:
    persona_file(None)
    calls = log_recalls(world, monkeypatch)

    await make(world, lambda p: BriefDraft(sections={}))

    assert calls == [(COMPETITOR_QUERY, FactKind.competitor)]


async def test_watch_outs_pool_of_eight_keep_first_three_resolved(
    world: World, persona_file: Any
) -> None:
    persona_file("Zorblax")
    world.memory.items = [i for i in world.memory.items if i.memory_id != "w_datahawk"]
    tags = [account_tag(ACC), fact_kind_tag(FactKind.competitor)]
    for n in range(4):  # ranks 1-4: no meeting anywhere, unresolvable
        world.memory.seed_fact(f"bad{n}", f"Rival vendor orphan {n}", tags=tags,
                               memory_type="observation")  # fmt: skip
    for n in range(1, 7):  # ranks 5-10: resolvable
        world.memory.seed_fact(
            f"good{n}",
            f"Rival vendor good {n}",
            tags=[*tags, meeting_tag("m3_finedge")],
            meeting_id="m3_finedge",
            meeting_date=date(2026, 8, 12),
        )

    _, llm = await make(world, lambda p: BriefDraft(sections={}))

    prompt = llm.calls[0].prompt
    assert "orphan" not in prompt
    # Pool = ranks 1-8 (4 bad + good1-good4); the first 3 that resolve, in rank order.
    good_lines = [ln for ln in prompt.splitlines() if "Rival vendor good" in ln]
    assert [ln.rsplit(" ", 1)[1] for ln in good_lines] == ["1", "2", "3"]


# ---- 3. timing log ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["memory", "no_memory"])
async def test_timing_line_emitted_once_with_all_keys_and_no_content(
    world: World, caplog: pytest.LogCaptureFixture, mode: str
) -> None:
    with caplog.at_level(logging.INFO):
        await make(world, mode=mode)

    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("brief.timing ")]
    assert len(lines) == 1
    record = next(r for r in caplog.records if r.getMessage().startswith("brief.timing "))
    assert record.name == "uvicorn.error"
    assert record.levelno == logging.INFO
    line = lines[0]
    for key in ("load_ms", "recall_ms", "reflect_ms", "resolve_ms", "mental_model_ms",
                "gather_ms", "p3_ms", "post_ms", "total_ms"):  # fmt: skip
        assert f" {key}=" in line
    assert f"meeting={M6} mode={mode}" in line
    assert all(part.split("=")[1].isdigit() for part in line.split()[3:])
    for content in ("Ananya", "DataHawk", "pricing deck", "Rahul"):
        assert content not in line


# ---- 4/7. mental-model citation --------------------------------------------------------------


async def test_mental_model_cites_latest_ingested_meeting_not_merely_done(world: World) -> None:
    with Session(world.engine) as s:
        m5 = s.get(Meeting, "m5_finedge")
        assert m5 is not None
        m5.ingested_at = None  # done, but never ingested: must not be cited
        s.add(m5)
        s.commit()

    brief, _ = await make(world)

    (wlo,) = section(brief, SectionKey.where_left_off)
    (c,) = wlo.citations
    assert (c.meeting_id, c.meeting_date) == ("m4_finedge", date(2026, 8, 27))
    assert c.label == "Relationship summary through Aug 27, 2026"
    assert c.quote and len(c.quote) <= 200


async def test_mental_model_dropped_when_nothing_is_ingested(world: World) -> None:
    with Session(world.engine) as s:
        for m in s.exec(select(Meeting)).all():
            m.ingested_at = None
            s.add(m)
        s.commit()

    _, llm = await make(world, lambda p: BriefDraft(sections={}))

    assert "[mm:" not in llm.calls[0].prompt


# ---- 5. concurrent upsert --------------------------------------------------------------------


def mini_brief(world: World, meeting_id: str, mode: str, brief_id: str, stamp: Any) -> Brief:
    return Brief(
        id=brief_id,
        meeting_id=meeting_id,
        mode=mode,  # type: ignore[arg-type]
        generated_at=stamp,
        sections=[],
        facts_used=0,
        preferences_applied=[],
    )


def rows(world: World) -> list[BriefRecord]:
    with Session(world.engine) as s:
        return list(s.exec(select(BriefRecord)).all())


def test_racing_saves_end_with_one_row_and_a_stable_id(world: World) -> None:
    # Both requests stamped before either saved: two different ids, same meeting and mode.
    id1, t1 = new_brief_stamp(world.session_factory, M6, "memory")
    id2, t2 = new_brief_stamp(world.session_factory, M6, "memory")
    assert id1 != id2

    first = save_brief(world.session_factory, mini_brief(world, M6, "memory", id1, t1))
    second = save_brief(world.session_factory, mini_brief(world, M6, "memory", id2, t2))

    (row,) = rows(world)
    assert first.id == id1 and second.id == id1 == row.id  # loser adopts the stored id
    assert row.content["id"] == id1


def test_threads_saving_the_same_meeting_and_mode_never_fail(world: World) -> None:
    barrier = threading.Barrier(4)
    errors: list[BaseException] = []
    saved: list[str] = []

    def work() -> None:
        try:
            brief_id, stamp = new_brief_stamp(world.session_factory, M6, "memory")
            barrier.wait(timeout=5)
            saved.append(
                save_brief(
                    world.session_factory, mini_brief(world, M6, "memory", brief_id, stamp)
                ).id
            )
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert errors == []
    (row,) = rows(world)
    assert set(saved) == {row.id}


def test_different_modes_coexist(world: World) -> None:
    for mode in ("memory", "no_memory"):
        brief_id, stamp = new_brief_stamp(world.session_factory, M6, mode)
        save_brief(world.session_factory, mini_brief(world, M6, mode, brief_id, stamp))

    assert {r.mode for r in rows(world)} == {"memory", "no_memory"}


def test_unique_index_creation_is_idempotent_and_dedupes_existing_rows(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:  # an old database: briefrecord WITHOUT the unique constraint
        conn.execute(text("DROP TABLE briefrecord"))
        conn.execute(
            text(
                "CREATE TABLE briefrecord (id VARCHAR PRIMARY KEY, meeting_id VARCHAR, "
                "mode VARCHAR, content JSON, created_at DATETIME)"
            )
        )
        for bid, mid, mode, ts in [
            ("br_old", "m6", "memory", "2026-09-01 10:00:00"),
            ("br_new", "m6", "memory", "2026-09-02 10:00:00"),
            ("br_other", "m6", "no_memory", "2026-09-01 10:00:00"),
        ]:
            conn.execute(
                text("INSERT INTO briefrecord VALUES (:i, :m, :mode, '{}', :ts)"),
                {"i": bid, "m": mid, "mode": mode, "ts": ts},
            )
        conn.execute(
            text(
                "INSERT INTO feedback (id, brief_id, section, action, created_at) "
                "VALUES ('fb1', 'br_old', 'agenda', 'up', '2026-09-01 11:00:00')"
            )
        )

    create_db_and_tables(engine)
    create_db_and_tables(engine)  # idempotent
    ensure_brief_unique_index(engine)

    with engine.connect() as conn:
        ids = {r[0] for r in conn.execute(text("SELECT id FROM briefrecord"))}
        assert ids == {"br_new", "br_other"}  # newest per (meeting, mode) kept
        assert (
            conn.execute(text("SELECT brief_id FROM feedback WHERE id='fb1'")).scalar() == "br_new"
        )
        indexes = {r[1]: r[2] for r in conn.execute(text("PRAGMA index_list(briefrecord)"))}
        assert indexes[BRIEF_UNIQUE_INDEX] == 1  # unique
    engine.dispose()


# ---- 6. empty briefs -------------------------------------------------------------------------


def make_everything_empty(world: World) -> None:
    """No external attendees (so no attendees section) and no overdue rows."""
    with Session(world.engine) as s:
        for a in s.exec(select(MeetingAttendee).where(MeetingAttendee.meeting_id == M6)).all():
            if a.contact_id != "c_priya":
                s.delete(a)
        for c in s.exec(select(Commitment)).all():
            s.delete(c)
        s.commit()
    world.memory.items.clear()
    world.memory.mental_models.clear()


def uncited_only(prompt: str) -> BriefDraft:
    return BriefDraft(sections={SectionKey.agenda: [item("Invented point", [])]})


async def test_empty_memory_brief_is_returned_but_not_persisted(world: World) -> None:
    make_everything_empty(world)

    brief, _ = await make(world, uncited_only)

    assert brief.sections == []
    assert rows(world) == []
    cached = await brief_module.get_cached_brief(
        M6, "memory", session_factory=world.session_factory
    )
    assert cached is None


def test_api_empty_brief_is_200_and_get_is_404(world: World) -> None:
    make_everything_empty(world)
    client = _install(world, ScriptedLLM(uncited_only))
    try:
        url = f"/api/meetings/{M6}/brief"
        post = client.post(url)
        assert post.status_code == 200 and post.json()["sections"] == []
        assert client.get(url).status_code == 404
    finally:
        main_module.app.dependency_overrides.clear()


async def test_non_empty_brief_still_persists_and_no_memory_is_unchanged(world: World) -> None:
    await make(world)
    await make(world, lambda p: BriefDraft(sections={}), mode="no_memory")

    assert {r.mode for r in rows(world)} == {"memory", "no_memory"}


async def test_no_memory_with_nothing_generated_is_still_persisted(world: World) -> None:
    make_everything_empty(world)

    brief, _ = await make(world, lambda p: BriefDraft(sections={}), mode="no_memory")

    assert brief.sections == []
    assert [r.mode for r in rows(world)] == ["no_memory"]  # rule applies to memory mode only


def _unique_indexes_on_brief_columns(engine: Any) -> list[str]:
    with engine.connect() as conn:
        found = []
        for row in conn.execute(text("PRAGMA index_list(briefrecord)")).all():
            if row[2]:
                cols = sorted(c[2] for c in conn.execute(text(f"PRAGMA index_info({row[1]})")))
                if cols == ["meeting_id", "mode"]:
                    found.append(row[1])
        return found


def test_fresh_database_ends_with_exactly_one_unique_index(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")

    create_db_and_tables(engine)
    create_db_and_tables(engine)

    assert len(_unique_indexes_on_brief_columns(engine)) == 1
    engine.dispose()


def test_old_schema_table_gets_exactly_one_unique_index(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'old2.db'}")
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE briefrecord"))
        conn.execute(
            text(
                "CREATE TABLE briefrecord (id VARCHAR PRIMARY KEY, meeting_id VARCHAR, "
                "mode VARCHAR, content JSON, created_at DATETIME)"
            )
        )
    assert _unique_indexes_on_brief_columns(engine) == []

    ensure_brief_unique_index(engine)
    ensure_brief_unique_index(engine)

    assert _unique_indexes_on_brief_columns(engine) == [BRIEF_UNIQUE_INDEX]
    engine.dispose()
