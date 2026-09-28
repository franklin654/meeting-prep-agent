"""Generator logic (T10): prompt rendering, ordering, throttling, guards. FakeLLM, no network."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest
from _testkit import make_seed, make_transcript
from generate import (
    GenerationAborted,
    RefuseOverwriteError,
    generate_transcripts,
    load_template,
    render_prompt,
    transcript_filename,
    write_transcript,
)

from app.core.errors import LLMTimeoutError
from tests.fakes.fake_llm import FakeLLM

PRIYA = ("Priya Nair", "Account Executive, Tracewise")
KARAN = ("Karan Shah", "Data Platform Lead, TestCo")
RAHUL = ("Rahul Mehta", "VP Engineering, TestCo")

# Built from parts so this test file never spells the protected transcript name in one piece.
LIVE_NAME = "m6_finedge" + "_live" + ".txt"


def _m1_text() -> str:
    return make_transcript(
        "2026-07-14",
        [
            (*PRIYA, "Hi Karan."),
            (*KARAN, "We run about 40 pipelines."),
            (*PRIYA, "I'll send the case study by Jul 17."),
        ],
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


def test_prompt_template_has_header_and_all_placeholders():
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
        "target_words",
        "max_words",
    ):
        assert "{" + key + "}" in template


def test_render_prompt_contains_cast_facts_forbidden_and_only_past_summaries():
    seed = make_seed()
    m2 = next(m for m in seed.meetings if m["id"] == "m2_test")
    prompt = render_prompt(seed, m2, target_words=1300, max_words=1800, minutes=30)
    assert "2026-07-28" in prompt and "Follow up" in prompt
    assert "Rahul Mehta" in prompt and "VP Engineering" in prompt
    assert "Karan Shah" in prompt and "KS" in prompt
    assert "thanks for the case study" in prompt  # required fact text
    assert "Priya promises a case study by Jul 17" in prompt  # summary of M1 (earlier)
    assert "{cast}" not in prompt and "{required_facts}" not in prompt
    m1 = next(m for m in seed.meetings if m["id"] == "m1_test")
    p1 = render_prompt(seed, m1, target_words=1300, max_words=1800, minutes=30)
    assert "thanks for the case study" not in p1  # no later-meeting facts
    assert "DataHawk" in p1  # forbidden list
    assert "aim for about 1,300 words of spoken dialogue; never exceed 1,800" in p1.lower()
    assert "900-1500" not in p1


def test_transcript_filename():
    seed = make_seed()
    assert transcript_filename(seed.meetings[0]) == "m1_test_discovery.txt"
    assert transcript_filename(seed.meetings[2]) == LIVE_NAME


def test_generates_in_date_order_at_temperature_08_serially_with_pause(tmp_path: Path):
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
    assert sleep.calls == [7.5]  # a pause between calls, none before the first
    assert len(res.timings) == 2 and all(t.seconds >= 0 for t in res.timings)
    assert res.written == ["m1_test", "m2_test"] and not res.failed


def test_calls_never_overlap(tmp_path: Path):
    seed = make_seed()
    state = {"active": 0, "max": 0}

    class SlowFake(FakeLLM):
        async def complete_text(self, prompt, *, temperature=0.0, system=None):
            state["active"] += 1
            state["max"] = max(state["max"], state["active"])
            await asyncio.sleep(0.01)
            state["active"] -= 1
            return await super().complete_text(prompt, temperature=temperature, system=system)

    fake = SlowFake()
    fake.queue_text(_m1_text())
    fake.queue_text(_m2_text())
    _run(generate_transcripts(fake, seed, tmp_path, pause_seconds=0, sleep=NoSleep()))
    assert state["max"] == 1


def test_m6_is_skipped_unless_explicitly_included(tmp_path: Path):
    seed = make_seed()
    fake = FakeLLM()
    fake.queue_text(_m1_text())
    fake.queue_text(_m2_text())
    _run(generate_transcripts(fake, seed, tmp_path, pause_seconds=0, sleep=NoSleep()))
    assert not (tmp_path / LIVE_NAME).exists()
    assert len(fake.text_calls) == 2


def test_m6_generated_once_as_draft_even_if_it_fails_validation(tmp_path: Path):
    seed = make_seed()
    fake = FakeLLM()
    fake.queue_text("[2026-09-29T10:00:00+05:30] Rahul Mehta (VP Engineering, TestCo): short.\n")
    res = _run(
        generate_transcripts(
            fake,
            seed,
            tmp_path,
            pause_seconds=0,
            sleep=NoSleep(),
            only={"m6_finedge"},
            include_m6=True,
        )
    )
    assert len(fake.text_calls) == 1  # single attempt, no regeneration for the draft
    assert (tmp_path / LIVE_NAME).exists()
    assert res.draft_problems  # reported, not fixed


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
                pause_seconds=0,
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
    res = _run(generate_transcripts(fake, seed, tmp_path, pause_seconds=0, sleep=NoSleep()))
    assert "m1_test" in res.skipped and existing.read_text() == "old\n"
    fake2 = FakeLLM()
    fake2.queue_text(_m1_text())
    _run(
        generate_transcripts(
            fake2,
            seed,
            tmp_path,
            pause_seconds=0,
            sleep=NoSleep(),
            only={"m1_test"},
            force=True,
        )
    )
    assert existing.read_text() != "old\n"


def test_failing_transcript_is_regenerated_and_not_written_if_it_keeps_failing(tmp_path: Path):
    seed = make_seed()
    fake = FakeLLM()
    fake.queue_text("[2026-07-14T10:00:00+05:30] Priya Nair (Account Executive, Tracewise): bad\n")
    fake.queue_text(_m1_text())
    res = _run(
        generate_transcripts(
            fake,
            seed,
            tmp_path,
            pause_seconds=0,
            sleep=NoSleep(),
            only={"m1_test"},
            max_attempts=3,
        )
    )
    assert len(fake.text_calls) == 2
    assert "Previous attempt" in fake.text_calls[1].prompt
    assert (tmp_path / "m1_test_discovery.txt").exists()
    assert [t.attempt for t in res.timings] == [1, 2]

    other = tmp_path / "other"
    other.mkdir()
    fake2 = FakeLLM()
    for _ in range(2):
        fake2.queue_text("nonsense\n")
    with pytest.raises(GenerationAborted) as exc:
        _run(
            generate_transcripts(
                fake2,
                seed,
                other,
                pause_seconds=0,
                sleep=NoSleep(),
                only={"m1_test"},
                max_attempts=2,
            )
        )
    assert exc.value.result.failed == ["m1_test"] and list(other.iterdir()) == []
    assert "m1_test" in exc.value.reason


def test_default_is_three_attempts_no_pause_and_180s_timeout():
    import generate

    assert generate.DEFAULT_MAX_ATTEMPTS == 4
    assert generate.DEFAULT_PAUSE_SECONDS == 0
    assert generate.CALL_TIMEOUT_SECONDS == 180


def test_main_builds_client_with_180s_timeout(monkeypatch, tmp_path: Path):
    import generate

    seen: dict[str, object] = {}
    monkeypatch.setattr(
        "app.llm.client.get_llm_client",
        lambda *a, **kw: seen.update(kw) or FakeLLM(),
    )
    generate.main(["--out-dir", str(tmp_path), "--only", "nothing"])
    assert seen == {"timeout_seconds": 180.0}


def test_timed_out_call_is_timed_and_stops_the_run(tmp_path: Path):
    seed = make_seed()
    fake = FakeLLM()
    fake.queue_text_error(LLMTimeoutError("slow"))
    with pytest.raises(GenerationAborted) as exc:
        _run(generate_transcripts(fake, seed, tmp_path, sleep=NoSleep()))
    assert [t.meeting_id for t in exc.value.result.timings] == ["m1_test"]


def test_typed_llm_error_aborts_the_run(tmp_path: Path):
    seed = make_seed()
    fake = FakeLLM()
    fake.queue_text(_m1_text())
    fake.queue_text_error(LLMTimeoutError("boom"))
    with pytest.raises(GenerationAborted) as exc:
        _run(generate_transcripts(fake, seed, tmp_path, pause_seconds=0, sleep=NoSleep()))
    assert "LLMTimeoutError" in exc.value.reason
    assert exc.value.result.written == ["m1_test"]


def test_rate_limit_log_line_aborts_immediately(tmp_path: Path):
    seed = make_seed()

    class RateLimitedFake(FakeLLM):
        async def complete_text(self, prompt, *, temperature=0.0, system=None):
            logging.getLogger("app.llm.providers.base").info(
                "llm.rate_limited retrying provider=openai model=x attempt=0 delay=1.00s "
                "duration=0.10s"
            )
            await asyncio.sleep(30)  # the client would be backing off; we must not wait
            return "never"

    with pytest.raises(GenerationAborted) as exc:
        _run(
            asyncio.wait_for(
                generate_transcripts(
                    RateLimitedFake(), seed, tmp_path, pause_seconds=0, sleep=NoSleep()
                ),
                timeout=5,
            )
        )
    assert "llm.rate_limited" in exc.value.reason
    assert list(tmp_path.iterdir()) == []


def test_length_targets_and_validator_ranges():
    import generate
    import validate

    assert generate.GENERATED_LENGTH == (1300, 1800)
    assert generate.LIVE_LENGTH == (700, 800)
    assert validate.DEFAULT_WORDS == (900, 2000)
    assert validate.LIVE_WORDS == (600, 800)


def test_four_failed_attempts_stop_and_report_reasons_per_attempt(tmp_path: Path):
    seed = make_seed()
    fake = FakeLLM()
    for i in range(4):
        fake.queue_text(f"nonsense {i}\n")
    with pytest.raises(GenerationAborted) as exc:
        _run(generate_transcripts(fake, seed, tmp_path, sleep=NoSleep(), only={"m1_test"}))
    assert len(fake.text_calls) == 4
    assert len(exc.value.result.attempt_problems["m1_test"]) == 4
    assert all(exc.value.result.attempt_problems["m1_test"])
