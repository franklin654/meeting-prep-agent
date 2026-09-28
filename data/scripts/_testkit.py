"""Helpers shared by test_generate.py and test_validate.py: a tiny synthetic seed."""

from __future__ import annotations

from validate import Seed

ACCOUNT = "acc_test"


def make_seed() -> Seed:
    contacts = [
        {
            "id": "c_priya",
            "name": "Priya Nair",
            "account_id": None,
            "role": "Account Executive",
            "aliases": [],
            "voice_and_traits": "runs the call",
        },
        {
            "id": "c_karan",
            "name": "Karan Shah",
            "account_id": ACCOUNT,
            "role": "Data Platform Lead",
            "aliases": ["KS"],
            "voice_and_traits": "enthusiastic",
        },
        {
            "id": "c_rahul",
            "name": "Rahul Mehta",
            "account_id": ACCOUNT,
            "role": "VP Engineering",
            "aliases": [],
            "voice_and_traits": "direct",
        },
    ]
    meetings = [
        {
            "id": "m1_test",
            "account_id": ACCOUNT,
            "date": "2026-07-14",
            "title": "Discovery",
            "attendees": ["c_priya", "c_karan"],
            "status": "done",
        },
        {
            "id": "m2_test",
            "account_id": ACCOUNT,
            "date": "2026-07-28",
            "title": "Follow up",
            "attendees": ["c_priya", "c_karan", "c_rahul"],
            "status": "done",
        },
        {
            "id": "m6_finedge",
            "account_id": ACCOUNT,
            "date": "2026-09-29",
            "title": "Live",
            "attendees": ["c_priya", "c_rahul"],
            "status": "upcoming",
        },
    ]
    beats = {
        "m1_test": {
            "meeting_id": "m1_test",
            "required_facts": [
                {
                    "id": "f_m1_case_promise",
                    "speaker": "c_priya",
                    "text": "Priya promises a case study by Jul 17",
                    "must_match": ["case study", "Jul 17|July 17"],
                },
                {
                    "id": "f_m1_pipes",
                    "speaker": "c_karan",
                    "text": "about 40 pipelines",
                    "must_match": ["40 pipelines"],
                    "beat": "B3",
                },
            ],
            "forbidden": ["DataHawk"],
        },
        "m2_test": {
            "meeting_id": "m2_test",
            "required_facts": [
                {
                    "id": "f_m2_case_ack",
                    "speaker": "c_karan",
                    "text": "thanks for the case study",
                    "must_match": ["case study"],
                },
            ],
            "forbidden": [],
        },
        "m6_finedge": {
            "meeting_id": "m6_finedge",
            "required_facts": [
                {
                    "id": "f_m6_x",
                    "speaker": "c_rahul",
                    "text": "we never did get that revised pricing deck",
                    "must_match": ["never did get", "pricing deck"],
                    "beat": "B1",
                },
            ],
            "forbidden": [],
        },
    }
    return Seed(
        company={
            "vendor": {
                "name": "Tracewise",
                "plans": [{"name": "Growth", "price_usd_per_year": 36000}],
                "pilot": {"price_usd": 5000},
            }
        },
        accounts=[{"id": ACCOUNT, "name": "TestCo", "deal_value_usd": 40000}],
        contacts=contacts,
        meetings=meetings,
        beats=beats,
        beat_defs=[{"id": "B3", "planted_in": ["m1_test"]}],
    )


def make_transcript(
    date: str,
    lines: list[tuple[str, str, str]],
    words: int = 1000,
    start_minute: int = 0,
    step_minutes: int = 1,
) -> str:
    """lines: (name, role_company, text). Pads the last utterance with filler to `words`."""
    have = sum(len(t.split()) for _, _, t in lines)
    out = []
    for i, (name, rc, text) in enumerate(lines):
        if i == len(lines) - 1 and have < words:
            text = text + " " + " ".join(["filler"] * (words - have))
        m = start_minute + i * step_minutes
        out.append(f"[{date}T{10 + m // 60:02d}:{m % 60:02d}:00+05:30] {name} ({rc}): {text}")
    return "\n".join(out) + "\n"
