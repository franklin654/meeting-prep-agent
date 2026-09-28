"""Validator rules from docs/synthetic-data-spec.md 'Validation checks' (T10). No network."""

from __future__ import annotations

from datetime import date

from _testkit import make_seed, make_transcript
from validate import (
    check_transcript,
    validate_all_texts,
    validate_cross,
    validate_seed,
)

PRIYA = ("Priya Nair", "Account Executive, Tracewise")
KARAN = ("Karan Shah", "Data Platform Lead, TestCo")
RAHUL = ("Rahul Mehta", "VP Engineering, TestCo")


def _m1(seed):
    return next(m for m in seed.meetings if m["id"] == "m1_test")


def _good_m1() -> str:
    return make_transcript(
        "2026-07-14",
        [
            (*PRIYA, "Hi Karan, good to see you."),
            (*KARAN, "We run about 40 pipelines today."),
            (*PRIYA, "Great. I'll send the case study by Jul 17."),
        ],
        step_minutes=12,
    )


def _check(seed, text, meeting="m1_test", **kw):
    m = next(x for x in seed.meetings if x["id"] == meeting)
    return check_transcript(seed, m, text, words=(900, 1500), duration=(20, 40), **kw)


def test_good_transcript_passes():
    assert _check(make_seed(), _good_m1()) == []


def test_missing_fact_pattern_fails():
    text = _good_m1().replace("case study", "one pager")
    problems = _check(make_seed(), text)
    assert any("f_m1_case_promise" in p for p in problems)


def test_forbidden_string_fails_with_word_boundaries():
    seed = make_seed()
    bad = _good_m1().replace("Hi Karan", "Hi Karan, DataHawk aside")
    assert any("forbidden" in p and "DataHawk" in p for p in _check(seed, bad))
    # 'designed' must not trip a forbidden 'signed'
    seed.beats["m1_test"]["forbidden"] = ["signed"]
    ok = _good_m1().replace("Hi Karan", "It was designed well")
    assert _check(seed, ok) == []


def test_speaker_must_be_attendee():
    text = (
        _good_m1()
        .replace("Hi Karan, good to see you.", "Hello all.")
        .replace(
            "[2026-07-14T10:00:00+05:30] Priya Nair (Account Executive, Tracewise)",
            "[2026-07-14T10:00:00+05:30] Rahul Mehta (VP Engineering, TestCo)",
        )
    )
    assert any("not an attendee" in p and "Rahul Mehta" in p for p in _check(make_seed(), text))


def test_timestamps_must_be_on_meeting_date_and_increase():
    seed = make_seed()
    wrong_day = _good_m1().replace("2026-07-14", "2026-07-15")
    assert any("date" in p for p in _check(seed, wrong_day))
    lines = _good_m1().splitlines()
    lines[1], lines[2] = lines[2], lines[1]
    assert any("increase" in p for p in _check(seed, "\n".join(lines) + "\n"))


def test_word_count_range():
    short = make_transcript(
        "2026-07-14",
        [(*PRIYA, "case study Jul 17"), (*KARAN, "40 pipelines")],
        words=10,
        step_minutes=25,
    )
    assert any("word count" in p for p in _check(make_seed(), short))
    long = make_transcript(
        "2026-07-14",
        [(*PRIYA, "I'll send the case study by Jul 17."), (*KARAN, "About 40 pipelines.")],
        words=1600,
        step_minutes=25,
    )
    assert any("word count" in p for p in _check(make_seed(), long))


def test_duration_range():
    fast = make_transcript(
        "2026-07-14",
        [(*PRIYA, "I'll send the case study by Jul 17."), (*KARAN, "About 40 pipelines.")],
        step_minutes=2,
    )
    assert any("duration" in p for p in _check(make_seed(), fast))


def test_unparseable_line_is_reported():
    text = _good_m1() + "this is not a transcript line\n"
    assert any("format" in p for p in _check(make_seed(), text))


def test_pricing_deck_never_received_before_m6():
    seed = make_seed()
    seed.beats["m1_test"]["forbidden"] = []
    for phrase in (
        "thanks for the pricing deck",
        "we got the pricing deck",
        "pricing deck received",
    ):
        text = _good_m1().replace("Hi Karan, good to see you.", f"Well, {phrase}.")
        assert any("pricing deck" in p for p in _check(seed, text)), phrase
    # promising it is fine
    ok = _good_m1().replace("Hi Karan, good to see you.", "I owe you a pricing deck.")
    assert _check(seed, ok) == []


def test_pricing_deck_rule_not_applied_to_m6():
    seed = make_seed()
    m6 = next(m for m in seed.meetings if m["id"] == "m6_finedge")
    text = make_transcript(
        "2026-09-29",
        [(*RAHUL, "We never did get that revised pricing deck, thanks for nothing.")],
        words=700,
        step_minutes=1,
    )
    problems = check_transcript(seed, m6, text, words=(600, 800), duration=None)
    assert problems == []


def test_promise_must_be_acknowledged_in_next_meeting():
    seed = make_seed()
    good = {
        "m1_test": _good_m1(),
        "m2_test": make_transcript(
            "2026-07-28",
            [(*KARAN, "Thanks for the case study."), (*PRIYA, "Anytime."), (*RAHUL, "Hello.")],
            step_minutes=12,
        ),
    }
    assert validate_cross(seed, good, demo_today=date(2026, 9, 28)) == []
    # drop the acknowledgement fact for m2 -> promise dangling
    seed.beats["m2_test"]["required_facts"] = []
    problems = validate_cross(seed, good, demo_today=date(2026, 9, 28))
    assert any("acknowledged" in p and "f_m1_case_promise" in p for p in problems)


def test_b1_deck_promise_is_exempt_from_ack_rule():
    seed = make_seed()
    seed.beats["m1_test"]["required_facts"].append(
        {
            "id": "f_deck_promise",
            "speaker": "c_priya",
            "text": "revised pricing deck by Sep 3",
            "must_match": ["pricing deck"],
            "beat": "B1",
        }
    )
    problems = validate_cross(seed, {}, demo_today=date(2026, 9, 28))
    assert not any("f_deck_promise" in p and "acknowledged" in p for p in problems)


def test_seed_checks_ids_dates_money():
    seed = make_seed()
    assert validate_seed(seed, demo_today=date(2026, 9, 28), strict_counts=False) == []
    seed.accounts[0]["deal_value_usd"] = 40000.5
    seed.contacts[0]["id"] = "priya"
    seed.meetings[0]["date"] = "2026-10-05"  # 'done' after demo_today
    problems = validate_seed(seed, demo_today=date(2026, 9, 28), strict_counts=False)
    assert any("integer USD" in p for p in problems)
    assert any("prefix" in p and "priya" in p for p in problems)
    assert any("m1_test" in p and "demo_today" in p for p in problems)


def test_seed_counts_enforced_in_strict_mode():
    problems = validate_seed(make_seed(), demo_today=date(2026, 9, 28), strict_counts=True)
    assert any("17 meetings" in p for p in problems)


def test_validate_all_texts_separates_m6():
    seed = make_seed()
    texts = {"m1_test": _good_m1(), "m6_finedge": "garbage\n"}
    report = validate_all_texts(seed, texts, demo_today=date(2026, 9, 28))
    assert report.per_meeting["m1_test"] == []
    assert "m6_finedge" not in report.per_meeting
    assert report.draft_problems  # m6 findings live in their own bucket
    assert "m2_test" in report.missing
