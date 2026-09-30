"""Smoke-test sandbox launch guards without starting API processes."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("sandbox_w.sh", "DATABASE_URL=sqlite:///./app.sandbox.db"),
        ("sandbox_r.sh", "DATABASE_URL=sqlite:///./app.sandbox-r.db"),
    ],
)
def test_sandbox_check_prints_resolved_safe_overrides(script: str, expected: str) -> None:
    result = subprocess.run(
        [str(ROOT / "scripts" / script), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert expected in result.stdout
    assert "BANK_ID=" in result.stdout
    assert "MEMORY_READ_ONLY=" in result.stdout


@pytest.mark.parametrize(
    ("script", "environment"),
    [
        ("sandbox_w.sh", {"DEMO_USER_ID": "user-demo-thomas"}),
        ("sandbox_w.sh", {"MEMORY_READ_ONLY": "true"}),
        ("sandbox_w.sh", {"DATABASE_URL": "sqlite:///./app.db"}),
        ("sandbox_r.sh", {"DEMO_USER_ID": "overhaul-test"}),
        ("sandbox_r.sh", {"MEMORY_READ_ONLY": "false"}),
        ("sandbox_r.sh", {"DATABASE_URL": "sqlite:///./app.db"}),
    ],
)
def test_sandbox_check_refuses_wrong_bank_or_read_write_r(
    script: str, environment: dict[str, str]
) -> None:
    result = subprocess.run(
        [str(ROOT / "scripts" / script), "--check"],
        cwd=ROOT,
        env={**os.environ, **environment},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Refusing" in result.stderr
