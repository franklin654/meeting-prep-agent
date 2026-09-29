"""B18: contact timeline API and dashboard `brief_ready` (fakes only, no network)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

import app.main as main_module
from app.api.deps import get_memory_service, get_session
from app.db import brief_repo, meetings_repo
from app.db import repository as repo
from app.db.models import Account, BriefRecord, Contact, Meeting
from app.memory.tags import (
    MemoryKind,
    account_tag,
    contact_tag,
    fact_kind_from_tags,
    fact_kind_tag,
    kind_tag,
    meeting_tag,
)
from app.schemas.api import ContactTimeline
from app.schemas.brief import Brief
from app.schemas.enums import FactKind
from tests.fakes.fake_memory_service import FakeMemoryService

ANITA = "c_anita"
DATES = {f"m{i}": date(2026, 8, 1) + timedelta(days=7 * (i - 1)) for i in range(1, 8)}


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    with Session(eng) as db:
        repo.create_account(db, Account(id="acc_a", name="A Co", industry="x", stage="eval"))
        repo.create_contact(db, Contact(id=ANITA, account_id="acc_a", name="Anita Rao", role="CFO"))
        repo.create_contact(db, Contact(id="c_empty", account_id="acc_a", name="Empty", role=None))
        for mid, d in DATES.items():
            repo.create_meeting(
                db,
                Meeting(
                    id=mid,
                    account_id="acc_a",
                    title=mid,
                    scheduled_at=datetime(d.year, d.month, d.day, 10, tzinfo=UTC),
                    status="done",
                ),
            )
    yield eng
    eng.dispose()


@pytest.fixture
def memory() -> FakeMemoryService:
    return FakeMemoryService()


@pytest.fixture
def client(engine: Engine, memory: FakeMemoryService) -> Iterator[TestClient]:
    def _session() -> Iterator[Session]:
        with Session(engine) as s:
            yield s

    overrides = main_module.app.dependency_overrides
    overrides[get_session] = _session
    overrides[get_memory_service] = lambda: memory
    yield TestClient(main_module.app)
    overrides.clear()


def _tags(meeting_id: str, *extra: str) -> list[str]:
    return [
        account_tag("acc_a"),
        contact_tag(ANITA),
        meeting_tag(meeting_id),
        kind_tag(MemoryKind.transcript),
        *extra,
    ]


def _seed(memory: FakeMemoryService, mid: str, memory_id: str, text: str, *extra: str) -> None:
    memory.seed_fact(
        memory_id, text, tags=_tags(mid, *extra), meeting_id=mid, meeting_date=DATES[mid]
    )


def _get(client: TestClient, contact_id: str = ANITA) -> ContactTimeline:
    response = client.get(f"/api/contacts/{contact_id}/timeline")
    assert response.status_code == 200, response.text
    return ContactTimeline.model_validate(response.json())


def test_fact_kind_from_tags() -> None:
    assert fact_kind_from_tags(["x", fact_kind_tag(FactKind.deal_fact)]) is FactKind.deal_fact
    assert fact_kind_from_tags(["x", "fact_kind:bogus"]) is None
    assert fact_kind_from_tags([]) is None


def test_unknown_contact_404(client: TestClient) -> None:
    response = client.get("/api/contacts/nope/timeline")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_no_facts_empty_entries(client: TestClient) -> None:
    timeline = _get(client, "c_empty")
    assert timeline.entries == []
    assert timeline.contact.id == "c_empty"


def test_acceptance_10_anita_m2_newest_first_linked(
    client: TestClient, memory: FakeMemoryService
) -> None:
    _seed(memory, "m1", "a", "Anita is the executive sponsor of the pilot.")
    _seed(memory, "m2", "b", "Anita's budget is 40000 USD.", fact_kind_tag(FactKind.deal_fact))
    _seed(memory, "m2", "c", "Anita ran a half marathon in spring.")
    timeline = _get(client)
    assert timeline.contact.name == "Anita Rao" and timeline.contact.role == "CFO"
    assert [e.citation.meeting_id for e in timeline.entries] == ["m2", "m2", "m1"]
    m2 = timeline.entries[0]
    assert m2.fact_kind is FactKind.deal_fact
    assert timeline.entries[1].fact_kind is None
    assert m2.learned_on == DATES["m2"]
    assert m2.citation.source_type == "meeting"
    assert m2.citation.meeting_date == DATES["m2"]
    assert m2.citation.label == "Call on Aug 8, 2026"
    assert m2.citation.quote == m2.text
    assert m2.citation.memory_id == "b"


def test_quote_truncated_to_200(client: TestClient, memory: FakeMemoryService) -> None:
    _seed(memory, "m1", "a", "word " * 100)
    entry = _get(client).entries[0]
    assert entry.citation.quote is not None and len(entry.citation.quote) <= 200


def test_preference_and_unresolvable_dropped(client: TestClient, memory: FakeMemoryService) -> None:
    _seed(memory, "m1", "keep", "Anita wants weekly updates.")
    memory.seed_fact(
        "pref",
        "Prefers short briefs.",
        tags=[contact_tag(ANITA), kind_tag(MemoryKind.preference)],
        meeting_id="m1",
        meeting_date=DATES["m1"],
    )
    memory.seed_fact(
        "orphan",
        "Observation with no source.",
        tags=[contact_tag(ANITA), kind_tag(MemoryKind.transcript)],
        memory_type="observation",
    )
    assert [e.citation.memory_id for e in _get(client).entries] == ["keep"]


def test_observation_resolved_through_sources(
    client: TestClient, memory: FakeMemoryService
) -> None:
    _seed(memory, "m3", "src", "Anita approved the security review.")
    memory.seed_fact(
        "obs",
        "Anita has approved the security review overall and is engaged.",
        tags=[contact_tag(ANITA), kind_tag(MemoryKind.transcript)],
        memory_type="observation",
        source_memory_ids=["src"],
    )
    entries = _get(client).entries
    assert {e.citation.memory_id for e in entries} == {"src", "obs"}
    assert all(e.citation.meeting_id == "m3" for e in entries)


@pytest.mark.parametrize(
    ("a", "b", "dup"),
    [
        ("Anita's budget is $40,000.", "anita's  BUDGET is 40000", True),  # normalised equal
        (
            "Anita said her annual budget is 40000 dollars",
            "Anita said her annual budget is 40000 dollars for the pilot",
            True,
        ),  # containment
        (
            "the pilot budget was approved by anita last week friday morning ok",
            "the pilot budget was approved by anita last week friday afternoon ok",
            True,
        ),  # jaccard 10/12 >= 0.8
        ("Anita ran a half marathon", "Anita likes golf on weekends", False),
        ("Anita is the CFO", "Anita is the CFO of a very large company overseas", False),
    ],
)
def test_dedupe_rules(
    client: TestClient, memory: FakeMemoryService, a: str, b: str, dup: bool
) -> None:
    _seed(memory, "m1", "a", a)
    _seed(memory, "m2", "b", b)
    assert len(_get(client).entries) == (1 if dup else 2)


def test_dedupe_keeps_earliest_meeting(client: TestClient, memory: FakeMemoryService) -> None:
    # Seeded newest first on purpose: the earliest meeting must still win.
    _seed(memory, "m4", "late", "Anita's budget is 40000 USD for the pilot.")
    _seed(memory, "m2", "early", "Anita's budget is 40000 USD for the pilot!")
    _seed(memory, "m3", "mid", "anita's budget is 40000 usd for the pilot")
    entries = _get(client).entries
    assert len(entries) == 1
    assert entries[0].citation.meeting_id == "m2"
    assert entries[0].learned_on == DATES["m2"]
    assert entries[0].citation.memory_id == "early"


def test_grouped_by_meeting_newest_first_rank_kept(
    client: TestClient, memory: FakeMemoryService
) -> None:
    _seed(memory, "m1", "a1", "alpha unique first fact about golf and travel plans")
    _seed(memory, "m3", "c1", "gamma unique rollout timeline for the data platform team")
    _seed(memory, "m1", "a2", "beta unique second fact about hiring and headcount growth")
    _seed(memory, "m3", "c2", "delta unique security questionnaire finished by the vendor")
    _seed(memory, "m2", "b1", "epsilon unique renewal discussion with procurement legal")
    entries = _get(client).entries
    assert [e.citation.meeting_id for e in entries] == ["m3", "m3", "m2", "m1", "m1"]
    assert [e.citation.memory_id for e in entries[:2]] == ["c1", "c2"]
    assert [e.citation.memory_id for e in entries[3:]] == ["a1", "a2"]


def test_cap_30_newest_meetings_first(client: TestClient, memory: FakeMemoryService) -> None:
    n = 0
    for mid in ["m1", "m2", "m3", "m4", "m5", "m6"]:
        for _ in range(13):  # 78 distinct facts
            n += 1
            _seed(memory, mid, f"f{n}", f"topic{n}x alpha{n}y beta{n}z gamma{n}w delta{n}v note")
    _seed(memory, "m6", "f_extra", "topicextra alphaextra betaextra gammaextra deltaextra note")
    _seed(memory, "m6", "f_extra2", "second extra1 second extra2 second extra3 second extra4 zz")
    entries = _get(client).entries
    assert len(entries) == 30
    meetings = [e.citation.meeting_id for e in entries]
    assert meetings[:15] == ["m6"] * 15
    assert meetings[15:28] == ["m5"] * 13
    assert meetings[28:] == ["m4"] * 2
    dates = [e.learned_on for e in entries]
    assert dates == sorted(dates, reverse=True)


# ---- dashboard brief_ready ----

T0 = datetime(2026, 9, 1, tzinfo=UTC)


def _add_brief(engine: Engine, meeting_id: str, mode: Literal["memory", "no_memory"]) -> None:
    content = Brief(
        id=f"br_{mode}",
        meeting_id=meeting_id,
        mode=mode,
        generated_at=T0,
        sections=[],
        facts_used=0,
        preferences_applied=[],
    ).model_dump(mode="json")
    with Session(engine) as db:
        repo.create_brief_record(
            db,
            BriefRecord(
                id=f"br_{mode}", meeting_id=meeting_id, mode=mode, content=content, created_at=T0
            ),
        )


def _ready(engine: Engine, meeting_id: str = "m2") -> bool:
    with Session(engine) as db:
        rows = {r.meeting.id: r.brief_ready for r in meetings_repo.list_meeting_rows(db)}
    return rows[meeting_id]


def _set_ingested(engine: Engine, meeting_id: str, at: datetime) -> None:
    with Session(engine) as db:
        meeting = repo.get_meeting(db, meeting_id)
        assert meeting is not None
        meeting.ingested_at = at
        db.add(meeting)
        db.commit()


def test_brief_ready_fresh_memory_brief(engine: Engine) -> None:
    _set_ingested(engine, "m1", T0 - timedelta(days=1))
    _add_brief(engine, "m2", "memory")
    assert _ready(engine) is True


def test_brief_ready_no_memory_only(engine: Engine) -> None:
    _add_brief(engine, "m2", "no_memory")
    assert _ready(engine) is False


def test_brief_ready_stale(engine: Engine) -> None:
    _add_brief(engine, "m2", "memory")
    _set_ingested(engine, "m1", T0 + timedelta(hours=1))
    assert _ready(engine) is False


def test_brief_ready_no_brief(engine: Engine) -> None:
    assert _ready(engine) is False


def test_brief_ready_agrees_with_get_fresh_brief(engine: Engine) -> None:
    _add_brief(engine, "m2", "memory")
    fresh = brief_repo.get_fresh_brief(lambda: Session(engine), "m2", "memory")
    assert (fresh is not None) == _ready(engine)
