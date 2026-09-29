"""Read the seeded company identity used for app-facing personalization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast


def company_data() -> dict[str, Any]:
    candidates = (
        Path("/data/seed/company.json"),
        Path(__file__).resolve().parents[3] / "data" / "seed" / "company.json",
    )
    for path in candidates:
        if path.is_file():
            return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    raise FileNotFoundError("data/seed/company.json is unavailable")


def ae_contact_id() -> str:
    return str(company_data()["ae"]["contact_id"])
