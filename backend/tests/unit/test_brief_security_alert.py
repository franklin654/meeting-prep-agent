"""T21b: the security-gap alert is one correct, code-built item and owns the alerts section."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlmodel import Session

from app.db.brief_repo import BriefInputs
from app.db.models import Account, Contact, Meeting
from app.memory.tags import account_tag, fact_kind_tag, meeting_tag
from app.schemas.brief import BriefDraft, SectionKey
from app.schemas.enums import FactKind
from app.schemas.memory import MemoryHit
from app.services.brief import _b5_alerts
from tests.unit.brief_world import ACC, World, evidence_ids, item, make_world
from tests.unit.test_brief_service import make, section

KEYWORDS = ["SOC 2", "data residency", "security", "RBI", "pen-test"]
SNEHA_FACT = (
    "Sneha Iyer requested on 2026-08-12 the SOC 2 Type II report and confirmation of "
    "India data residency before any pilot."
)


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    yield from make_world(tmp_path)


def contact(cid: str, name: str, account: str | None = "acc") -> Contact:
    return Contact(id=cid, account_id=account, name=name)


def meeting(mid: str, day: date, title: str) -> Meeting:
    return Meeting(
        id=mid,
        account_id="acc",
        title=title,
        scheduled_at=datetime(day.year, day.month, day.day, 10, tzinfo=UTC),
        status="done",
    )


def hit(mid: str, text: str, day: date, memory_id: str | None = None) -> MemoryHit:
    return MemoryHit(
        memory_id=memory_id or f"mem_{mid}",
        text=text,
        meeting_id=mid,
        meeting_date=day,
        tags=[],
    )


ANITA = contact("c_anita", "Anita Desai")
RAHUL = contact("c_rahul", "Rahul Mehta")
KARAN = contact("c_karan", "Karan Shah")
SNEHA = contact("c_sneha", "Sneha Iyer")
PRIYA = contact("c_priya", "Priya Nair", None)
D1, D2, D3 = date(2026, 7, 14), date(2026, 8, 12), date(2026, 8, 27)


def inputs(
    attendees: list[Contact] | None = None,
    attended: dict[str, set[str]] | None = None,
) -> BriefInputs:
    meetings = [
        meeting("m1", D1, "Discovery"),
        meeting("m3", D2, "Technical deep dive"),
        meeting("m4", D3, "Pilot scoping"),
        meeting("m6", date(2026, 9, 30), "Next"),
    ]
    return BriefInputs(
        meeting=meetings[-1],
        account=Account(id="acc", name="FinEdge", industry="x", size="y", stage="z"),  # type: ignore[call-arg]
        attendees=attendees or [PRIYA, RAHUL, ANITA, KARAN],
        account_meetings=meetings,
        all_meetings=meetings,
        other_accounts=[],
        account_contacts=[RAHUL, ANITA, KARAN, SNEHA],
        attendee_ids_by_meeting=attended
        or {
            "m1": {"c_priya", "c_rahul", "c_karan"},
            "m3": {"c_priya", "c_rahul", "c_karan", "c_sneha"},
            "m4": {"c_priya", "c_rahul", "c_karan"},
        },
        open_commitments=[],
        pinned_ask_answers=[],
    )


def test_exact_item_with_raiser_who_is_not_an_upcoming_attendee() -> None:
    (alert,) = _b5_alerts(inputs(), [hit("m3", SNEHA_FACT, D2)], [], KEYWORDS)
    assert alert.text == (
        "Sneha Iyer raised a SOC 2 and data residency concern on Aug 12; "
        "Anita Desai was not on that call."
    )
    assert [c.meeting_id for c in alert.citations] == ["m3"]
    assert alert.citations[0].quote == SNEHA_FACT
    assert alert.contact_ids == ["c_anita"]


def test_best_matching_hit_in_meeting_sets_topic_and_quote() -> None:
    generic = "Sneha Iyer requests confirmation of the approved channel and redaction for security."
    hits = [hit("m3", generic, D2, "a_first"), hit("m3", SNEHA_FACT, D2, "z_last")]
    (alert,) = _b5_alerts(inputs(), hits, [], KEYWORDS)
    assert alert.text == (
        "Sneha Iyer raised a SOC 2 and data residency concern on Aug 12; "
        "Anita Desai was not on that call."
    )
    assert alert.citations[0].quote == SNEHA_FACT


def test_several_raisers_and_meetings_yield_one_earliest_item() -> None:
    hits = [
        hit("m4", "Karan Shah raised an RBI concern on 2026-08-27.", D3),
        hit("m3", SNEHA_FACT, D2),
        hit("m1", "Rahul Mehta raised a security concern in July.", D1),
    ]
    alerts = _b5_alerts(inputs(), hits, [], KEYWORDS)
    assert len(alerts) == 1
    assert alerts[0].text.startswith("Rahul Mehta raised a security concern on Jul 14;")
    assert "Anita Desai" in alerts[0].text


def test_never_lists_source_attendees_our_people_or_the_raiser() -> None:
    attended = {"m3": {"c_priya", "c_rahul", "c_karan", "c_anita", "c_sneha"}}
    assert _b5_alerts(inputs(attended=attended), [hit("m3", SNEHA_FACT, D2)], [], KEYWORDS) == []
    (alert,) = _b5_alerts(
        inputs(attendees=[PRIYA, ANITA, SNEHA]),
        [hit("m3", SNEHA_FACT, D2)],
        [],
        KEYWORDS,
    )
    assert "Priya" not in alert.text and "Sneha Iyer was not" not in alert.text
    assert alert.text.endswith("Anita Desai was not on that call.")


def test_multiple_absent_names_joined_with_and() -> None:
    attended = {"m3": {"c_priya", "c_karan", "c_sneha"}}
    (alert,) = _b5_alerts(inputs(attended=attended), [hit("m3", SNEHA_FACT, D2)], [], KEYWORDS)
    assert "Rahul Mehta and Anita Desai was not on that call." in alert.text


def test_discovery_summary_hit_is_rejected() -> None:
    summary = (
        "Priya Nair led a discovery meeting with Rahul Mehta where security and SOC 2 "
        "concerns were raised."
    )
    assert _b5_alerts(inputs(), [hit("m1", summary, D1)], [], KEYWORDS) == []
    summary2 = "The discovery meeting covered security; Rahul Mehta raised SOC 2."
    assert _b5_alerts(inputs(), [hit("m1", summary2, D1)], [], KEYWORDS) == []


def test_name_only_mentioned_later_is_not_the_raiser() -> None:
    text = "The team noted that Karan Shah raised an RBI concern."
    assert _b5_alerts(inputs(), [hit("m4", text, D3)], [], KEYWORDS) == []
    quote_by_sneha = "Sneha Iyer said the RBI audit is mandatory, Karan Shah agreed."
    (alert,) = _b5_alerts(inputs(), [hit("m3", quote_by_sneha, D2)], [], KEYWORDS)
    assert alert.text.startswith("Sneha Iyer raised a RBI concern")


def test_our_own_people_and_non_security_hits_do_not_qualify() -> None:
    ours = "Priya Nair raised SOC 2 as a topic."
    other = "Sneha Iyer requested the pricing deck."
    assert _b5_alerts(inputs(), [hit("m3", ours, D2), hit("m3", other, D2)], [], KEYWORDS) == []


def test_absence_citation_only_when_about_absent_person() -> None:
    about_anita = hit("m4", "Karan said Anita hasn't been in the security conversations.", D3)
    about_rahul = hit("m4", "Karan said Rahul hasn't been in the security calls.", D3, "mem_r")
    (alert,) = _b5_alerts(inputs(), [hit("m3", SNEHA_FACT, D2)], [about_rahul], KEYWORDS)
    assert len(alert.citations) == 1
    (alert,) = _b5_alerts(inputs(), [hit("m3", SNEHA_FACT, D2)], [about_anita], KEYWORDS)
    assert [c.meeting_id for c in alert.citations] == ["m3", "m4"]


async def test_alerts_section_holds_only_the_security_item(world: World) -> None:
    with Session(world.engine) as session:
        session.add(Contact(id="c_sneha", account_id=ACC, name="Sneha Iyer"))
        session.commit()
    world.memory.seed_fact(
        "security_m3",
        SNEHA_FACT,
        tags=[account_tag(ACC), fact_kind_tag(FactKind.deal_fact), meeting_tag("m3_finedge")],
        meeting_id="m3_finedge",
        meeting_date=date(2026, 8, 12),
    )

    def draft(prompt: str) -> BriefDraft:
        assert evidence_ids(prompt, "DataHawk"), "stray alert must have evidence to be drafted"
        return BriefDraft(
            sections={
                SectionKey.alerts: [
                    item(
                        "A decision is needed by Oct 31; procurement is handled by Vikram Rao.",
                        evidence_ids(prompt, "DataHawk")[:1],
                    )
                ]
            }
        )

    brief, _ = await make(world, draft)
    alerts = section(brief, SectionKey.alerts)
    assert [i.id.split("-")[0] for i in alerts] == ["b5"]
    assert all("DataHawk" not in i.text for i in alerts)
    assert alerts[0].text.startswith(
        "Sneha Iyer raised a SOC 2 and data residency concern on Aug 12"
    )


async def test_no_qualifying_hit_means_no_alerts_section(world: World) -> None:
    def draft(prompt: str) -> BriefDraft:
        return BriefDraft(
            sections={
                SectionKey.alerts: [item("Stray warning", evidence_ids(prompt, "DataHawk")[:1])]
            }
        )

    brief, _ = await make(world, draft)
    assert section(brief, SectionKey.alerts) == []
