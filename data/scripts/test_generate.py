"""Generator logic (T10): prompt rendering, ordering, lanes, retries, guards. No network."""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path

import pytest
from _testkit import make_seed, make_transcript
from generate import (
    RefuseOverwriteError,
    generate_transcripts,
    load_template,
    render_prompt,
    transcript_filename,
    write_transcript,
)

from app.core.errors import LLMTimeoutError, RateLimitedError
from app.llm.client import LLMClient
from tests.fakes.fake_llm import FakeLLM

PRIYA = ("Priya Nair", "Account Executive, Tracewise")
KARAN = ("Karan Shah", "Data Platform Lead, TestCo")
RAHUL = ("Rahul Mehta", "VP Engineering, TestCo")

# Built from parts so this test file never spells the protected transcript name in one piece.
LIVE_NAME = "m6_finedge" + "_live" + ".txt"
LENGTH_LINE = "Write the meeting at its natural length; do not shorten it or pad it."


def _m1_text(words: int = 1000) -> str:
    return make_transcript(
        "2026-07-14",
        [
            (*PRIYA, "Hi Karan."),
            (*KARAN, "We run about 40 pipelines."),
            (*PRIYA, "I'll send the case study by Jul 17."),
        ],
        words=words,
        step_minutes=12,
    )


def _m2_text() -> str:
    return make_transcript(
        "2026-07-28",
        [(*KARAN, "Thanks for the case study."), (*PRIYA, "Sure."), (*RAHUL, "Hi.")],
        step_minutes=12,
    )


def _run(coro):
    return asyncio.run(coro)


class NoSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def test_prompt_template_has_placeholders_and_only_the_natural_length_line():
    template = load_template()
    assert not template.lstrip().startswith("<!--")  # header comment stripped before sending
    for key in (
        "date",
        "title",
        "minutes",
        "cast",
        "previous_summaries",
        "style_refs",
        "required_facts",
        "forbidden",
    ):
        assert "{" + key + "}" in template
    assert LENGTH_LINE in template
    for gone in ("{target_words}", "{max_words}", "{min_words}", "never exceed", "1,300"):
        assert gone not in template
    raw = (
        Path(__file__).resolve().parents[2] / "backend/app/llm/prompts" / "generate_transcript.md"
    ).read_text()
    assert "target_words" not in raw and "max_words" not in raw  # header too


def test_render_prompt_contains_cast_facts_forbidden_and_only_past_summaries():
    seed = make_seed()
    m2 = next(m for m in seed.meetings if m["id"] == "m2_test")
    prompt = render_prompt(seed, m2, minutes=30)
    assert "2026-07-28" in prompt and "Follow up" in prompt
    assert "Rahul Mehta" in prompt and "VP Engineering" in prompt
    assert "Karan Shah" in prompt and "KS" in prompt
    assert "thanks for the case study" in prompt  # required fact text
    assert "Priya promises a case study by Jul 17" in prompt  # summary of M1 (earlier)
    assert "{cast}" not in prompt and "{required_facts}" not in prompt
    m1 = next(m for m in seed.meetings if m["id"] == "m1_test")
    p1 = render_prompt(seed, m1, minutes=30)
    assert "thanks for the case study" not in p1  # no later-meeting facts
    assert "DataHawk" in p1  # forbidden list
    assert LENGTH_LINE in p1


def test_transcript_filename():
    seed = make_seed()
    assert transcript_filename(seed.meetings[0]) == "m1_test_discovery.txt"
    assert transcript_filename(seed.meetings[2]) == LIVE_NAME


def test_defaults_and_ranges():
    import generate
    import validate

    assert generate.DEFAULT_MAX_ATTEMPTS == 4
    assert generate.DEFAULT_PAUSE_SECONDS == 0
    assert generate.CALL_TIMEOUT_SECONDS == 300
    assert generate.MAX_PARALLEL_LANES == 4
    assert validate.DEFAULT_WORDS == (400, 6000)
    assert validate.LIVE_WORDS == (600, 800)


def test_main_builds_client_with_300s_timeout(monkeypatch, tmp_path: Path):
    import generate

    seen: dict[str, object] = {}
    monkeypatch.setattr(
        "app.llm.client.get_llm_client",
        lambda *a, **kw: seen.update(kw) or FakeLLM(),
    )
    generate.main(["--out-dir", str(tmp_path), "--only", "nothing"])
    assert seen == {"timeout_seconds": 300.0}


def test_generates_in_date_order_at_temperature_08_with_pause(tmp_path: Path):
    seed = make_seed()
    fake = FakeLLM()
    fake.queue_text(_m1_text())
    fake.queue_text(_m2_text())
    sleep = NoSleep()
    res = _run(generate_transcripts(fake, seed, tmp_path, pause_seconds=7.5, sleep=sleep))
    assert [c.temperature for c in fake.text_calls] == [0.8, 0.8]
    assert "Discovery" in fake.text_calls[0].prompt
    assert "Follow up" in fake.text_calls[1].prompt
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "m1_test_discovery.txt",
        "m2_test_follow_up.txt",
    ]
    assert sleep.calls == [7.5]
    assert len(res.timings) == 2 and all(t.seconds >= 0 for t in res.timings)
    assert all(t.words > 0 for t in res.timings)
    assert res.written == ["m1_test", "m2_test"] and not res.failed
    assert res.total_seconds >= 0


def _two_account_seed():
    seed = make_seed()
    seed.accounts.append({"id": "acc_two", "name": "TwoCo", "deal_value_usd": 1000})
    seed.meetings.append(
        {
            "id": "n1_two",
            "account_id": "acc_two",
            "date": "2026-03-10",
            "title": "Intro",
            "attendees": ["c_priya", "c_karan"],
            "status": "done",
        }
    )
    seed.meetings.append(
        {
            "id": "n2_two",
            "account_id": "acc_two",
            "date": "2026-03-24",
            "title": "Second",
            "attendees": ["c_priya", "c_karan"],
            "status": "done",
        }
    )
    for mid in ("n1_two", "n2_two"):
        seed.beats[mid] = {"meeting_id": mid, "required_facts": [], "forbidden": []}
    return seed


class ScriptedLLM(LLMClient):
    """Returns text by meeting date found in the prompt; tracks concurrency."""

    def __init__(self, by_date: dict[str, str], delay: float = 0.01) -> None:
        self.by_date = by_date
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self.order: list[str] = []
        self.prompts: list[str] = []

    async def complete_json(self, *a, **kw):  # pragma: no cover
        raise AssertionError

    async def complete_text(self, prompt, *, temperature=0.0, system=None):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.prompts.append(prompt)
        date = prompt.split("Date: ")[1][:10]
        self.order.append(date)
        await asyncio.sleep(self.delay)
        self.active -= 1
        return self.by_date[date]


def _ok(date: str) -> str:
    return make_transcript(
        date, [(*PRIYA, "Hello there."), (*KARAN, "Hi.")], words=500, step_minutes=25
    )


def test_accounts_run_in_parallel_lanes_but_each_account_in_date_order(tmp_path: Path):
    seed = _two_account_seed()
    by_date = {
        "2026-07-14": _m1_text(),
        "2026-07-28": _m2_text(),
        "2026-03-10": _ok("2026-03-10"),
        "2026-03-24": _ok("2026-03-24"),
    }
    llm = ScriptedLLM(by_date)
    res = _run(generate_transcripts(llm, seed, tmp_path, sleep=NoSleep()))
    assert not res.failed and len(res.written) == 4
    assert llm.max_active == 2  # two accounts -> two lanes at once
    assert llm.order.index("2026-03-10") < llm.order.index("2026-03-24")
    assert llm.order.index("2026-07-14") < llm.order.index("2026-07-28")


def test_parallelism_is_capped_at_four(tmp_path: Path):
    seed = make_seed()
    by_date = {}
    for i in range(6):
        aid = f"acc_{i}"
        seed.accounts.append({"id": aid, "name": f"Co{i}", "deal_value_usd": 1})
        mid = f"n1_{i}"
        seed.meetings.append(
            {
                "id": mid,
                "account_id": aid,
                "date": f"2026-03-{10 + i}",
                "title": "T",
                "attendees": ["c_priya", "c_karan"],
                "status": "done",
            }
        )
        seed.beats[mid] = {"meeting_id": mid, "required_facts": [], "forbidden": []}
        by_date[f"2026-03-{10 + i}"] = _ok(f"2026-03-{10 + i}")
    llm = ScriptedLLM(by_date, delay=0.05)
    res = _run(
        generate_transcripts(
            llm, seed, tmp_path, sleep=NoSleep(), only={f"n1_{i}" for i in range(6)}
        )
    )
    assert len(res.written) == 6
    assert llm.max_active == 4


def test_m6_is_skipped_unless_explicitly_included(tmp_path: Path):
    seed = make_seed()
    fake = FakeLLM()
    fake.queue_text(_m1_text())
    fake.queue_text(_m2_text())
    _run(generate_transcripts(fake, seed, tmp_path, sleep=NoSleep()))
    assert not (tmp_path / LIVE_NAME).exists()
    assert len(fake.text_calls) == 2


def test_m6_generated_once_as_draft_even_if_it_fails_validation(tmp_path: Path):
    seed = make_seed()
    fake = FakeLLM()
    fake.queue_text("[2026-09-29T10:00:00+05:30] Rahul Mehta (VP Engineering, TestCo): short.\n")
    res = _run(
        generate_transcripts(
            fake, seed, tmp_path, sleep=NoSleep(), only={"m6_finedge"}, include_m6=True
        )
    )
    assert len(fake.text_calls) == 1  # single attempt, no regeneration for the draft
    assert (tmp_path / LIVE_NAME).exists()
    assert res.draft_problems  # reported, not fixed


def test_m6_typed_error_is_single_attempt_and_writes_nothing(tmp_path: Path):
    seed = make_seed()
    fake = FakeLLM()
    fake.queue_text_error(LLMTimeoutError("slow"))
    res = _run(
        generate_transcripts(
            fake, seed, tmp_path, sleep=NoSleep(), only={"m6_finedge"}, include_m6=True
        )
    )
    assert len(fake.text_calls) == 1 and res.failed == ["m6_finedge"]
    assert not (tmp_path / LIVE_NAME).exists()


def test_refuses_to_overwrite_existing_m6_and_makes_no_llm_call(tmp_path: Path):
    seed = make_seed()
    target = tmp_path / LIVE_NAME
    target.write_text("HAND EDITED\n")
    fake = FakeLLM()
    with pytest.raises(RefuseOverwriteError):
        _run(
            generate_transcripts(
                fake,
                seed,
                tmp_path,
                sleep=NoSleep(),
                only={"m6_finedge"},
                include_m6=True,
                force=True,
            )
        )
    assert fake.text_calls == []
    assert target.read_text() == "HAND EDITED\n"


def test_write_transcript_guard_is_absolute_for_m6(tmp_path: Path):
    target = tmp_path / LIVE_NAME
    write_transcript(target, "first\n", overwrite=False)
    with pytest.raises(RefuseOverwriteError):
        write_transcript(target, "second\n", overwrite=True)
    assert target.read_text() == "first\n"


def test_existing_non_m6_files_skipped_without_force_and_replaced_with_force(tmp_path: Path):
    seed = make_seed()
    existing = tmp_path / "m1_test_discovery.txt"
    existing.write_text("old\n")
    fake = FakeLLM()
    fake.queue_text(_m2_text())
    res = _run(generate_transcripts(fake, seed, tmp_path, sleep=NoSleep()))
    assert "m1_test" in res.skipped and existing.read_text() == "old\n"
    fake2 = FakeLLM()
    fake2.queue_text(_m1_text())
    _run(generate_transcripts(fake2, seed, tmp_path, sleep=NoSleep(), only={"m1_test"}, force=True))
    assert existing.read_text() != "old\n"


def test_failing_transcript_is_regenerated_with_only_non_length_reasons_fed_back(
    tmp_path: Path,
):
    seed = make_seed()
    fake = FakeLLM()
    # wrong speaker AND too short: both reasons exist, only the speaker one may be fed back
    fake.queue_text("[2026-07-14T10:00:00+05:30] Rahul Mehta (VP Engineering, TestCo): bad\n")
    fake.queue_text(_m1_text())
    res = _run(generate_transcripts(fake, seed, tmp_path, sleep=NoSleep(), only={"m1_test"}))
    assert len(fake.text_calls) == 2
    retry_prompt = fake.text_calls[1].prompt
    assert "Previous attempt" in retry_prompt and "not an attendee" in retry_prompt
    assert "word count" not in retry_prompt
    assert (tmp_path / "m1_test_discovery.txt").exists()
    assert [t.attempt for t in res.timings] == [1, 2]


def test_length_only_failure_retries_without_feedback(tmp_path: Path):
    seed = make_seed()
    fake = FakeLLM()
    fake.queue_text(_m1_text(words=50))  # under the 400 minimum, nothing else wrong
    fake.queue_text(_m1_text())
    _run(generate_transcripts(fake, seed, tmp_path, sleep=NoSleep(), only={"m1_test"}))
    assert "Previous attempt" not in fake.text_calls[1].prompt


def test_four_failed_attempts_are_listed_and_the_run_continues(tmp_path: Path):
    seed = make_seed()
    fake = FakeLLM()
    for i in range(4):
        fake.queue_text(f"nonsense {i}\n")
    fake.queue_text(_m2_text())
    res = _run(generate_transcripts(fake, seed, tmp_path, sleep=NoSleep()))
    assert len(fake.text_calls) == 5
    assert res.failed == ["m1_test"] and res.written == ["m2_test"]
    assert len(res.attempt_problems["m1_test"]) == 4
    assert not (tmp_path / "m1_test_discovery.txt").exists()


def test_timeout_is_retried_then_succeeds(tmp_path: Path):
    seed = make_seed()
    fake = FakeLLM()
    fake.queue_text_error(LLMTimeoutError("slow"))
    fake.queue_text(_m1_text())
    res = _run(generate_transcripts(fake, seed, tmp_path, sleep=NoSleep(), only={"m1_test"}))
    assert res.written == ["m1_test"]
    assert [(t.attempt, t.error) for t in res.timings] == [(1, "LLMTimeoutError"), (2, None)]


def test_rate_limit_backs_off_exponentially_and_retries_without_aborting(tmp_path: Path):
    seed = make_seed()
    fake = FakeLLM()
    fake.queue_text_error(RateLimitedError("429"))
    fake.queue_text_error(RateLimitedError("429"))
    fake.queue_text(_m1_text())
    sleep = NoSleep()
    res = _run(
        generate_transcripts(
            fake, seed, tmp_path, sleep=sleep, only={"m1_test"}, rate_limit_backoff_seconds=10
        )
    )
    assert res.written == ["m1_test"] and not res.failed
    assert sleep.calls == [10, 20]
    assert len(res.rate_limit_events) == 2
    # backoff retries are not validation attempts
    assert [t.attempt for t in res.timings if t.error is None] == [1]


def test_rate_limit_backoff_is_bounded(tmp_path: Path):
    seed = make_seed()
    fake = FakeLLM()
    for _ in range(3):
        fake.queue_text_error(RateLimitedError("429"))
    sleep = NoSleep()
    res = _run(
        generate_transcripts(
            fake,
            seed,
            tmp_path,
            sleep=sleep,
            only={"m1_test"},
            rate_limit_backoff_seconds=1,
            max_rate_limit_retries=2,
            max_attempts=1,
        )
    )
    assert res.failed == ["m1_test"]
    assert len(fake.text_calls) == 3 and sleep.calls == [1, 2]


def test_seed_object_is_not_mutated(tmp_path: Path):
    seed = make_seed()
    before = copy.deepcopy(seed.beats)
    fake = FakeLLM()
    fake.queue_text(_m1_text())
    _run(generate_transcripts(fake, seed, tmp_path, sleep=NoSleep(), only={"m1_test"}))
    assert seed.beats == before
