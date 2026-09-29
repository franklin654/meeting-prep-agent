"""Tolerance and safe failure logging for structured Hindsight reports."""

from datetime import date

from app.schemas.ask import ReflectAnswer
from app.schemas.memory import ReflectResult
from app.schemas.reasoning import ContradictionReport, GapReport
from app.schemas.reflect import parse_reflect_result
from app.services.evidence import ObjectionReport


def result(structured: dict[str, object] | None, text: str = "raw") -> ReflectResult:
    return ReflectResult(text=text, structured=structured, sources=[], structured_error=None)


def test_r1_accepts_wrapped_list_yes_no_dates_optional_and_extra_fields() -> None:
    parsed = parse_reflect_result(
        "R1",
        result({
            "data": {
                "objections": {
                    "items": [{
                        "concern": "SOC 2",
                        "raised_by": "Sneha",
                        "raised_on": "August 12, 2026",
                        "resolved": "no",
                        "unknown": "ignored",
                    }]
                },
                "extra": "ignored",
            }
        }),
        ObjectionReport,
    )

    assert isinstance(parsed, ObjectionReport)
    objection = parsed.objections[0]
    assert objection.raised_on == date(2026, 8, 12)
    assert objection.resolved is False
    assert objection.resolution is None


def test_r2_accepts_bool_and_multiple_date_formats_and_ignores_extra() -> None:
    parsed = parse_reflect_result(
        "R2",
        result({
            "contradictions": [{
                "topic": "budget",
                "earlier_value": "$40K",
                "earlier_date": "08/12/2026",
                "new_value": "$75K",
                "new_date": "Sep 29, 2026",
                "summary": "Budget changed",
                "resolved": True,
            }]
        }),
        ContradictionReport,
    )

    assert isinstance(parsed, ContradictionReport)
    assert parsed.contradictions[0].earlier_date == date(2026, 8, 12)
    assert parsed.contradictions[0].new_date == date(2026, 9, 29)


def test_r5_ignores_extra_fields() -> None:
    parsed = parse_reflect_result(
        "R5", result({"answer": "It is $75K.", "confident": True, "note": "extra"}), ReflectAnswer
    )

    assert parsed == ReflectAnswer(answer="It is $75K.", confident=True)


def test_r3_allows_missing_optional_date_and_parses_long_date() -> None:
    parsed = parse_reflect_result(
        "R3",
        result({
            "gaps": [{
                "concern": "SOC 2",
                "raised_by": "Sneha",
                "not_heard_by": ["Anita"],
                "ignored": "extra",
            }]
        }),
        GapReport,
    )

    assert isinstance(parsed, GapReport)
    assert parsed.gaps[0].answered_on is None


def test_failure_log_reports_paths_keys_and_types_without_output_values(caplog) -> None:
    parsed = parse_reflect_result(
        "R1",
        result({"objections": [{"concern": "SECRET VALUE", "resolved": "maybe"}]}, "PRIVATE TEXT"),
        ObjectionReport,
    )

    assert parsed is None
    line = caplog.text
    assert "stage=R1" in line
    assert "objections.0.raised_by" in line
    assert "bool_parsing" in line
    assert "top_level_keys=['objections']" in line
    assert "raw_text_length=12" in line
    assert "SECRET VALUE" not in line and "PRIVATE TEXT" not in line
