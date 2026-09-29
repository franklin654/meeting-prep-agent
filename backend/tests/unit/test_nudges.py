from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api.deps import get_session
from app.db import repository
from app.db.models import Account, BriefRecord, Commitment, Contact, Meeting
from app.main import app
from app.schemas.enums import CommitmentStatus, Owner

TODAY = date(2026, 9, 28)


@pytest.fixture
def engine() -> Iterator[object]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def client(engine: object, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    from app.services import nudges

    monkeypatch.setattr(nudges, "today", lambda: TODAY)

    def session_dependency() -> Iterator[Session]:
        with Session(engine) as session:  # type: ignore[arg-type]
            yield session

    app.dependency_overrides[get_session] = session_dependency
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _add_meeting(
    session: Session,
    meeting_id: str,
    *,
    account_id: str = "acc_open",
    when: date,
    status: str,
    title: str | None = None,
    attendees: tuple[str, ...] = (),
    ingested_at: datetime | None = None,
) -> None:
    session.add(
        Meeting(
            id=meeting_id,
            account_id=account_id,
            title=title or meeting_id,
            scheduled_at=datetime(when.year, when.month, when.day, 10, tzinfo=UTC),
            status=status,
            ingested_at=ingested_at,
        )
    )
    session.flush()
    for contact_id in attendees:
        session.add(repository.add_attendee(session, meeting_id, contact_id))


def _add_brief(session: Session, meeting_id: str, created: datetime) -> None:
    content = {
        "id": f"br_{meeting_id}",
        "meeting_id": meeting_id,
        "mode": "memory",
        "generated_at": created.isoformat(),
        "sections": [],
        "facts_used": 0,
        "preferences_applied": [],
    }
    session.add(
        BriefRecord(
            id=f"br_{meeting_id}",
            meeting_id=meeting_id,
            mode="memory",
            content=content,
            created_at=created,
        )
    )
    session.commit()


def _seed(client_engine: object, *, extras: bool = True) -> None:
    with Session(client_engine) as session:  # type: ignore[arg-type]
        session.add_all(
            [
                Account(
                    id="acc_open",
                    name="FinEdge Payments",
                    industry="fintech",
                    size=20,
                    stage="evaluation",
                ),
                Account(
                    id="acc_closed", name="Closed Co", industry="x", size=5, stage="closed_won"
                ),
                Contact(
                    id="c_sneha",
                    account_id="acc_open",
                    name="Sneha Iyer",
                    role="IT Security Manager",
                ),
                Contact(id="c_longest", account_id="acc_open", name="Long Silent", role="CFO"),
                Contact(id="c_second", account_id="acc_open", name="Second Silent", role="CTO"),
                Contact(
                    id="c_upcoming", account_id="acc_open", name="Upcoming Contact", role="Lead"
                ),
                Contact(id="c_rep", account_id=None, name="Priya Nair", role="Account Executive"),
            ]
        )
        session.commit()
        _add_meeting(
            session,
            "m_done_aug12",
            when=date(2026, 8, 12),
            status="done",
            attendees=("c_sneha", "c_second", "c_upcoming"),
        )
        _add_meeting(
            session, "m_done_aug01", when=date(2026, 8, 1), status="done", attendees=("c_longest",)
        )
        _add_meeting(
            session, "m_done_jul20", when=date(2026, 7, 20), status="done", attendees=("c_second",)
        )
        _add_meeting(
            session,
            "m6_finedge",
            when=date(2026, 9, 29),
            status="upcoming",
            title="Pilot decision",
            attendees=("c_upcoming", "c_rep"),
        )
        _add_meeting(
            session, "m_earlier", when=date(2026, 9, 29), status="upcoming", title="Earlier meeting"
        )
        _add_meeting(
            session, "m_later", when=date(2026, 10, 1), status="upcoming", title="Later meeting"
        )
        _add_meeting(
            session, "m_closed", account_id="acc_closed", when=date(2026, 9, 29), status="upcoming"
        )
        if extras:
            _add_meeting(
                session, "m_ready2", when=date(2026, 9, 30), status="upcoming", title="Ready two"
            )
            _add_meeting(
                session, "m_ready3", when=date(2026, 10, 2), status="upcoming", title="Ready three"
            )
            _add_meeting(
                session, "m_ready4", when=date(2026, 10, 3), status="upcoming", title="Ready four"
            )
        for meeting_id in ["m6_finedge", *(["m_ready2", "m_ready3", "m_ready4"] if extras else [])]:
            _add_brief(session, meeting_id, datetime(2026, 9, 20, tzinfo=UTC))
        for i, due in enumerate(
            [date(2026, 8, 1), date(2026, 9, 3), date(2026, 9, 10), date(2026, 9, 18)]
        ):
            session.add(
                Commitment(
                    id=f"com_{i}",
                    account_id="acc_open",
                    meeting_id="m_done_aug12",
                    owner=Owner.us,
                    text=f"Our task {i}",
                    due_date=due,
                    status=CommitmentStatus.open,
                    source_quote="quote",
                )
            )
        session.add_all(
            [
                Commitment(
                    id="com_them",
                    account_id="acc_open",
                    meeting_id="m_done_aug12",
                    owner=Owner.them,
                    text="Customer task",
                    due_date=date(2026, 8, 1),
                    source_quote="quote",
                ),
                Commitment(
                    id="com_closed",
                    account_id="acc_closed",
                    meeting_id="m_closed",
                    owner=Owner.us,
                    text="Closed task",
                    due_date=date(2026, 8, 1),
                    source_quote="quote",
                ),
                Commitment(
                    id="com_today",
                    account_id="acc_open",
                    meeting_id="m_done_aug12",
                    owner=Owner.us,
                    text="Due today",
                    due_date=TODAY,
                    source_quote="quote",
                ),
            ]
        )
        session.commit()


def test_nudges_order_caps_and_exclusions(client: TestClient, engine: object) -> None:
    _seed(engine)
    response = client.get("/api/nudges")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 8
    assert [row["kind"] for row in rows] == [
        "overdue_commitment",
        "overdue_commitment",
        "overdue_commitment",
        "brief_ready",
        "brief_ready",
        "brief_ready",
        "brief_ready",
        "silent_contact",
    ]
    assert rows[0]["text"] == "Task 0 is 58 days overdue (FinEdge Payments)"
    assert rows[0]["link"] == "/meetings/m6_finedge"
    assert rows[1]["text"] == "Task 1 is 25 days overdue (FinEdge Payments)"
    assert rows[3]["text"] == "Brief ready: Pilot decision - FinEdge Payments, Sep 29"
    assert rows[7]["text"].endswith("hasn't been on a call for 58 days")
    assert "Closed Co" not in str(rows)
    assert "Customer task" not in str(rows)


def test_silent_contacts_capped_at_two_and_upcoming_attendee_excluded(
    client: TestClient, engine: object
) -> None:
    _seed(engine, extras=False)
    with Session(engine) as session:  # type: ignore[arg-type]
        for commitment in repository.list_overdue_commitments(session):
            session.delete(commitment)
        session.commit()
    rows = client.get("/api/nudges").json()
    silent = [row for row in rows if row["kind"] == "silent_contact"]
    assert len(silent) == 2
    assert silent[0]["text"].startswith("Long Silent")
    assert silent[1]["text"].startswith("Second Silent")
    assert silent[0]["link"] == "/contacts/c_longest"
    assert all("Upcoming Contact" not in row["text"] for row in silent)


def test_empty_nudges_returns_empty_list(client: TestClient, engine: object) -> None:
    with Session(engine) as session:  # type: ignore[arg-type]
        session.add(Account(id="empty", name="Empty", industry="x", size=None, stage="discovery"))
        session.commit()
    assert client.get("/api/nudges").json() == []


def test_overdue_nudge_links_to_dashboard_when_account_has_no_upcoming_meeting(
    client: TestClient, engine: object
) -> None:
    _seed(engine, extras=False)
    with Session(engine) as session:  # type: ignore[arg-type]
        for commitment in repository.list_overdue_commitments(session):
            session.delete(commitment)
        session.add(
            Account(
                id="acc_no_upcoming",
                name="No upcoming account",
                industry="x",
                size=2,
                stage="evaluation",
            )
        )
        session.commit()
        session.add(
            Commitment(
                id="com_no_upcoming",
                account_id="acc_no_upcoming",
                meeting_id="m_done_aug12",
                owner=Owner.us,
                text="Send the proposal",
                due_date=date(2026, 9, 1),
                source_quote="quote",
            )
        )
        session.commit()
    rows = client.get("/api/nudges").json()
    assert rows[0]["kind"] == "overdue_commitment"
    assert rows[0]["link"] == "/"
