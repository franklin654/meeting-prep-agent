"""Lightweight sanity check for data/seed/*.json (ticket T09).

This is NOT the real validator (that's T10's data/scripts/validate.py, which will
check transcripts against beats.json's must_match/forbidden rules). This script
only checks that the seed JSON files are well-formed and internally consistent:

- every file parses as JSON and has the expected top-level shape
- account/contact/meeting ids are unique and use the documented prefixes
- every meeting's account_id exists in accounts.json
- every meeting's attendees exist in contacts.json
- beats.json's meeting_id references exist in meetings.json
- every planted beat (B1-B6) is referenced by at least one required_fact

Run with: uv run pytest data/scripts/test_seed_sanity.py
(or plain: python data/scripts/test_seed_sanity.py)
"""

from __future__ import annotations

import json
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"

EXPECTED_ACCOUNT_IDS = {"acc_finedge", "acc_nimbus", "acc_veda", "acc_orbit"}
EXPECTED_MEETING_COUNT = 17
EXPECTED_CONTACT_COUNT_MIN = 13  # 12 from the spec table + Priya (our AE)
EXPECTED_BEATS = {"B1", "B2", "B3", "B4", "B5", "B6"}


def _load(name: str):
    path = SEED_DIR / name
    assert path.exists(), f"missing seed file: {path}"
    with path.open() as f:
        return json.load(f)


def test_company_json_loads():
    company = _load("company.json")
    assert company["vendor"]["name"] == "Tracewise"
    assert company["ae"]["name"] == "Priya Nair"


def test_accounts_json():
    accounts = _load("accounts.json")
    ids = {a["id"] for a in accounts}
    assert ids == EXPECTED_ACCOUNT_IDS, ids
    for a in accounts:
        assert a["id"].startswith("acc_")
        assert isinstance(a["deal_value_usd"], int)
        assert a["stage"] in {"discovery", "evaluation", "closed_won", "closed_lost"}


def test_contacts_json():
    contacts = _load("contacts.json")
    ids = [c["id"] for c in contacts]
    assert len(ids) == len(set(ids)), "duplicate contact ids"
    assert len(contacts) >= EXPECTED_CONTACT_COUNT_MIN
    accounts = {a["id"] for a in _load("accounts.json")}
    for c in contacts:
        assert c["id"].startswith("c_")
        # account_id is null for our own people (Priya, Arjun); otherwise must exist
        if c["account_id"] is not None:
            assert c["account_id"] in accounts, c


def test_meetings_json():
    meetings = _load("meetings.json")
    assert len(meetings) == EXPECTED_MEETING_COUNT, len(meetings)

    accounts = {a["id"] for a in _load("accounts.json")}
    contacts = {c["id"] for c in _load("contacts.json")}

    ids = [m["id"] for m in meetings]
    assert len(ids) == len(set(ids)), "duplicate meeting ids"

    for m in meetings:
        assert m["account_id"] in accounts, m
        assert m["status"] in {"upcoming", "done"}, m
        assert len(m["attendees"]) > 0
        for attendee in m["attendees"]:
            assert attendee in contacts, f"{m['id']} has unknown attendee {attendee}"
        # date format YYYY-MM-DD
        y, mo, d = m["date"].split("-")
        assert len(y) == 4 and len(mo) == 2 and len(d) == 2

    # account-level counts from the spec
    by_account: dict[str, list] = {}
    for m in meetings:
        by_account.setdefault(m["account_id"], []).append(m)
    assert len(by_account["acc_finedge"]) == 6  # 5 seeded + M6
    assert len(by_account["acc_nimbus"]) == 4
    assert len(by_account["acc_veda"]) == 4  # V1-V3 + upcoming V4
    assert len(by_account["acc_orbit"]) == 3

    # M6 and V4 are the two upcoming meetings
    upcoming = {m["id"] for m in meetings if m["status"] == "upcoming"}
    assert upcoming == {"m6_finedge", "v4_veda"}, upcoming


def test_beats_json():
    beats_doc = _load("beats.json")
    meeting_entries = beats_doc["meetings"]
    meeting_ids = {m["id"] for m in _load("meetings.json")}
    contact_ids = {c["id"] for c in _load("contacts.json")}

    seen_beats: set[str] = set()
    seen_fact_ids: set[str] = set()

    for entry in meeting_entries:
        assert entry["meeting_id"] in meeting_ids, entry["meeting_id"]
        assert "required_facts" in entry
        assert "forbidden" in entry
        for fact in entry["required_facts"]:
            assert fact["id"] not in seen_fact_ids, f"duplicate fact id {fact['id']}"
            seen_fact_ids.add(fact["id"])
            assert fact["speaker"] in contact_ids, fact
            assert isinstance(fact["must_match"], list) and fact["must_match"]
            if fact.get("beat"):
                seen_beats.add(fact["beat"])

    assert seen_beats == EXPECTED_BEATS, f"beats missing from required_facts: {EXPECTED_BEATS - seen_beats}"

    top_level_beats = {b["id"] for b in beats_doc["beats"]}
    assert top_level_beats == EXPECTED_BEATS, top_level_beats

    # V4 has no transcript yet, so it must not appear in beats.json's meetings list
    assert "v4_veda" not in {e["meeting_id"] for e in meeting_entries}


def _run_as_script():
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {t.__name__}: {e}")
    if failures:
        raise SystemExit(f"{failures} sanity check(s) failed")
    print("All seed sanity checks passed.")


if __name__ == "__main__":
    _run_as_script()
