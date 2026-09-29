import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from app import demo_tools


def _plan(tmp_path: Path) -> demo_tools.RestorePlan:
    snapshot = tmp_path / "phase4-clean"
    snapshot.mkdir()
    snapshot_db = snapshot / "app.db"
    archive = snapshot / "hindsight-data.tar.gz"
    manifest = snapshot / "manifest.json"
    with sqlite3.connect(snapshot_db) as db:
        db.execute("CREATE TABLE sample (value TEXT)")
        db.execute("INSERT INTO sample VALUES ('snapshot')")
    archive.write_bytes(b"fake archive")
    manifest.write_text(json.dumps({
        "hindsight_volume": "meeting-prep-agent_hindsight-data",
        "hindsight_image_digest": "ghcr.io/vectorize-io/hindsight@sha256:" + "a" * 64,
    }))
    return demo_tools.RestorePlan(
        "phase4-clean",
        tmp_path / "backend" / "app.db",
        "meeting-prep-agent_hindsight-data",
        archive,
        snapshot_db,
        manifest,
        "ghcr.io/vectorize-io/hindsight@sha256:" + "a" * 64,
    )


def test_snapshot_name_rejects_paths() -> None:
    with pytest.raises(demo_tools.DemoToolError):
        demo_tools._check_name("../other")


def test_restore_without_confirmations_is_dry_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = _plan(tmp_path)
    calls: list[list[str]] = []

    def fake_runner(argv: list[str], _cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    did_restore = demo_tools.restore_confirmed(
        plan,
        confirm_db=None,
        confirm_volume=None,
        confirm_snapshot=None,
        runner=fake_runner,
        api_stopped=True,
    )

    output = capsys.readouterr().out
    assert did_restore is False
    assert str(plan.db_target) in output
    assert plan.volume_target in output
    assert str(plan.archive_target) in output
    assert "Dry run" in output
    assert calls == []


@pytest.mark.parametrize(
    "confirmations",
    [
        ("wrong-db", "meeting-prep-agent_hindsight-data", "archive"),
        ("db", "wrong-volume", "archive"),
        ("db", "meeting-prep-agent_hindsight-data", "wrong-archive"),
        ("db", None, "archive"),
        (None, "meeting-prep-agent_hindsight-data", "archive"),
        ("db", "meeting-prep-agent_hindsight-data", None),
    ],
)
def test_restore_refuses_inexact_or_incomplete_confirmation(
    tmp_path: Path, confirmations: tuple[str | None, str | None, str | None]
) -> None:
    plan = _plan(tmp_path)
    calls: list[list[str]] = []

    def fake_runner(argv: list[str], _cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    with pytest.raises(demo_tools.DemoToolError, match="all three confirmations"):
        demo_tools.restore_confirmed(
            plan,
            confirm_db=confirmations[0],
            confirm_volume=confirmations[1],
            confirm_snapshot=confirmations[2],
            runner=fake_runner,
            api_stopped=True,
        )
    assert calls == []


def test_restore_refuses_when_api_is_running_even_with_exact_targets(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    calls: list[list[str]] = []

    def fake_runner(argv: list[str], _cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    with pytest.raises(demo_tools.DemoToolError, match="API is running"):
        demo_tools.restore_confirmed(
            plan,
            confirm_db=str(plan.db_target),
            confirm_volume=plan.volume_target,
            confirm_snapshot=str(plan.archive_target),
            runner=fake_runner,
            api_stopped=False,
        )
    assert calls == []


def test_sqlite_backup_api_copies_a_database_without_file_copy(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    destination = tmp_path / "snapshot.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE marker (value TEXT)")
        db.execute("INSERT INTO marker VALUES ('kept')")

    demo_tools._backup_sqlite(source, destination)

    with sqlite3.connect(f"file:{destination}?mode=ro", uri=True) as db:
        assert db.execute("SELECT value FROM marker").fetchone() == ("kept",)
