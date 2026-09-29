"""Tolerance and safe diagnostics for structured Hindsight reflect results."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ValidationError

from app.schemas.memory import ReflectResult

logger = logging.getLogger(__name__)


def _date_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    normalized = value.strip()
    try:
        return date.fromisoformat(normalized[:10])
    except ValueError:
        pass
    for fmt in (
        "%B %d, %Y",
        "%b %d, %Y",
        "%B %d %Y",
        "%b %d %Y",
        "%m/%d/%Y",
        "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            continue
    return value


def _normalize(value: Any, *, key: str = "") -> Any:
    if key in {"raised_on", "answered_on", "resolved_on", "earlier_date", "new_date"}:
        return _date_value(value)
    if key == "resolved" and isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"yes", "true", "1"}:
            return True
        if lowered in {"no", "false", "0"}:
            return False
    if isinstance(value, dict):
        return {child_key: _normalize(child, key=child_key) for child_key, child in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def _unwrap(payload: Any, schema: type[BaseModel]) -> Any:
    if not isinstance(payload, dict):
        return payload
    fields = set(schema.model_fields)
    if fields.intersection(payload):
        normalized = dict(payload)
    else:
        normalized = payload
        for value in payload.values():
            found = _unwrap(value, schema)
            if isinstance(found, dict) and fields.intersection(found):
                normalized = found
                break

    for field_name in schema.model_fields:
        if field_name not in normalized:
            continue
        value = normalized[field_name]
        if isinstance(value, dict):
            lists = [candidate for candidate in value.values() if isinstance(candidate, list)]
            if len(lists) == 1:
                normalized[field_name] = lists[0]
    return _normalize(normalized)


def parse_reflect_result(
    stage: str,
    result: ReflectResult,
    schema: type[BaseModel],
) -> BaseModel | None:
    """Validate a reflect result once; invalid output is logged safely and dropped."""
    payload = _unwrap(result.structured, schema)
    keys = sorted(str(key) for key in payload) if isinstance(payload, dict) else []
    try:
        if payload is None:
            raise ValueError("no structured output")
        return schema.model_validate(payload)
    except (ValidationError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            details = exc.errors(include_input=False, include_url=False)
            paths = [".".join(str(part) for part in error["loc"]) for error in details]
            error_types = sorted({str(error["type"]) for error in details})
        else:
            paths = []
            error_types = [type(exc).__name__]
        logger.warning(
            "reflect.validation_failed stage=%s field_paths=%s error_types=%s "
            "top_level_keys=%s raw_text_length=%d",
            stage,
            paths,
            error_types,
            keys,
            len(result.text),
        )
        return None
