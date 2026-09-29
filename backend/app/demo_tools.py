"""Snapshot and guarded restore tools for the local demo state.

Snapshot archives use SQLite's online backup API and the already-pulled,
digest-pinned Hindsight image as a read-only tar runner. A restore is dry-run
unless all three target confirmations exactly match the printed plan.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import sqlite3
import subprocess
import tarfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
REPO_ROOT = BACKEND_DIR.parent
DB_PATH = BACKEND_DIR / "app.db"
BACKUP_ROOT = Path.home() / "meeting-prep-backups"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
HINDSIGHT_DATA_PATH = "/home/hindsight/.pg0"
HINDSIGHT_HEALTH_URL = "http://127.0.0.1:8888/health"
API_ADDRESS = ("127.0.0.1", 8000)
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
IMAGE_RE = re.compile(r"^\s+image:\s+(\S+@sha256:[0-9a-f]{64})", re.MULTILINE)
Runner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]


class DemoToolError(RuntimeError):
    """A safe-to-display error from a demo snapshot/restore command."""


@dataclass(frozen=True)
class RestorePlan:
    name: str
    db_target: Path
    volume_target: str
    archive_target: Path
    snapshot_db: Path
    manifest_path: Path
    image_digest: str


def _run(argv: Sequence[str], cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    """Run a command without echoing its environment or command output."""
    try:
        return subprocess.run(
            list(argv), cwd=cwd, check=True, capture_output=True, text=True
        )
    except subprocess.CalledProcessError as exc:
        raise DemoToolError(
            f"Command failed ({exc.returncode}): {argv[0]} {argv[1]}"
        ) from exc


def _check_name(name: str) -> None:
    if not NAME_RE.fullmatch(name):
        raise DemoToolError("NAME must contain only letters, digits, dot, underscore, or hyphen.")


def _check_api_stopped() -> None:
    try:
        with socket.create_connection(API_ADDRESS, timeout=0.5):
            raise DemoToolError(
                "API is running on 127.0.0.1:8000; stop it before snapshot/restore."
            )
    except OSError:
        return


def _pinned_image() -> str:
    content = COMPOSE_FILE.read_text(encoding="utf-8")
    match = IMAGE_RE.search(content)
    if match is None:
        raise DemoToolError("Could not find a digest-pinned Hindsight image in docker-compose.yml.")
    return match.group(1)


def _running_service_details(runner: Runner) -> tuple[str, str, str]:
    """Return Hindsight container id, volume name, and pinned image after inspection."""
    result = runner(["docker", "compose", "ps", "--all", "-q", "hindsight"], REPO_ROOT)
    container_ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(container_ids) != 1:
        raise DemoToolError(
            f"Expected one Compose Hindsight container; found {len(container_ids)}."
        )
    inspected = json.loads(runner(["docker", "inspect", container_ids[0]], REPO_ROOT).stdout)
    if len(inspected) != 1:
        raise DemoToolError("Could not inspect the Compose Hindsight container.")
    container = inspected[0]
    volume_names = [
        mount["Name"]
        for mount in container.get("Mounts", [])
        if mount.get("Destination") == HINDSIGHT_DATA_PATH and mount.get("Type") == "volume"
    ]
    if len(volume_names) != 1:
        raise DemoToolError(
            "Could not identify the Hindsight data volume from its container mount."
        )
    image = _pinned_image()
    image_id = runner(
        ["docker", "image", "inspect", image, "--format", "{{.Id}}"], REPO_ROOT
    ).stdout.strip()
    if container.get("Image") != image_id:
        raise DemoToolError(
            "The running Hindsight container does not use the Compose-pinned image digest."
        )
    return container_ids[0], volume_names[0], image


def _wait_healthy(timeout_seconds: int = 90) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urlopen(HINDSIGHT_HEALTH_URL, timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, URLError):
            time.sleep(1)
    raise DemoToolError("Hindsight did not return HTTP 200 from /health within 90 seconds.")


def _backup_sqlite(source_path: Path, destination_path: Path) -> None:
    if destination_path.exists():
        raise DemoToolError(f"Refusing to overwrite existing file: {destination_path}")
    with sqlite3.connect(f"file:{source_path}?mode=ro", uri=True) as source:
        with sqlite3.connect(destination_path) as destination:
            source.backup(destination)


def _row_counts(database_path: Path) -> dict[str, int]:
    with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True) as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        return {
            table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in tables
        }


def _verify_archive(path: Path) -> None:
    try:
        with tarfile.open(path, "r:gz") as archive:
            archive.getmembers()
    except (OSError, tarfile.TarError) as exc:
        raise DemoToolError(f"Hindsight volume archive validation failed: {exc}") from exc


def run_snapshot(name: str, runner: Runner = _run) -> Path:
    _check_name(name)
    _check_api_stopped()
    snapshot_dir = BACKUP_ROOT / name
    if snapshot_dir.exists():
        raise DemoToolError(f"Refusing to overwrite existing snapshot directory: {snapshot_dir}")

    container_id, volume_name, image = _running_service_details(runner)
    snapshot_dir.mkdir(parents=True)
    database_copy = snapshot_dir / "app.db"
    archive = snapshot_dir / "hindsight-data.tar.gz"
    manifest_path = snapshot_dir / "manifest.json"

    # Confirm tar exists in the pinned image before taking the Hindsight service down.
    runner(
        ["docker", "run", "--rm", "--pull=never", "--entrypoint", "tar", image, "--version"],
        REPO_ROOT,
    )
    _backup_sqlite(DB_PATH, database_copy)

    stopped = False
    try:
        runner(["docker", "compose", "stop", "hindsight"], REPO_ROOT)
        stopped = True
        runner(
            [
                "docker", "run", "--rm", "--pull=never",
                "--mount", f"type=volume,src={volume_name},dst=/snapshot,readonly",
                "--mount", f"type=bind,src={snapshot_dir},dst=/backup",
                "--entrypoint", "tar", image,
                "-czf", "/backup/hindsight-data.tar.gz", "-C", "/snapshot", ".",
            ],
            REPO_ROOT,
        )
        _verify_archive(archive)
    finally:
        if stopped:
            runner(["docker", "compose", "start", "hindsight"], REPO_ROOT)
            _wait_healthy()

    commit = runner(["git", "rev-parse", "HEAD"], REPO_ROOT).stdout.strip()
    manifest = {
        "name": name,
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "git_commit": commit,
        "hindsight_image_digest": image,
        "hindsight_volume": volume_name,
        "row_counts": _row_counts(database_copy),
        "files": {"sqlite": database_copy.name, "hindsight_archive": archive.name},
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"SQLite: {database_copy}")
    print(f"Hindsight archive: {archive}")
    print(f"Manifest: {manifest_path}")
    print(f"Hindsight image: {image}")
    print(f"Hindsight volume: {volume_name}")
    print(f"SQLite bytes: {database_copy.stat().st_size}")
    print(f"Archive bytes: {archive.stat().st_size}")
    return snapshot_dir


def build_restore_plan(name: str) -> RestorePlan:
    _check_name(name)
    snapshot_dir = BACKUP_ROOT / name
    manifest_path = snapshot_dir / "manifest.json"
    snapshot_db = snapshot_dir / "app.db"
    archive = snapshot_dir / "hindsight-data.tar.gz"
    if not manifest_path.is_file() or not snapshot_db.is_file() or not archive.is_file():
        raise DemoToolError(f"Snapshot {name!r} is incomplete or does not exist at {snapshot_dir}.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DemoToolError(f"Cannot read snapshot manifest: {exc}") from exc
    volume = manifest.get("hindsight_volume")
    image = manifest.get("hindsight_image_digest")
    if not isinstance(volume, str) or not volume:
        raise DemoToolError("Snapshot manifest has no Hindsight volume name.")
    if not isinstance(image, str) or "@sha256:" not in image:
        raise DemoToolError("Snapshot manifest has no digest-pinned Hindsight image.")
    return RestorePlan(name, DB_PATH, volume, archive, snapshot_db, manifest_path, image)


def print_restore_plan(plan: RestorePlan) -> None:
    print(f"Snapshot: {plan.name}")
    print(f"SQLite target: {plan.db_target}")
    print(f"Hindsight volume target: {plan.volume_target}")
    print(f"Hindsight archive: {plan.archive_target}")
    print("Dry run: no files, database rows, containers, or volumes changed.")
    print("To execute, pass all three exact confirmations:")
    print(f"  --confirm-db {plan.db_target}")
    print(f"  --confirm-volume {plan.volume_target}")
    print(f"  --confirm-snapshot {plan.archive_target}")


def restore_confirmed(
    plan: RestorePlan,
    *,
    confirm_db: str | None,
    confirm_volume: str | None,
    confirm_snapshot: str | None,
    runner: Runner = _run,
    api_stopped: bool | None = None,
) -> bool:
    """Restore only after exact path/name confirmations and an API-down check.

    Returns false for a no-confirmation dry run. The destructive path is not
    used by unit tests or the Phase 5 ticket until a human passes all targets.
    """
    print_restore_plan(plan)
    supplied = (confirm_db, confirm_volume, confirm_snapshot)
    if all(value is None for value in supplied):
        return False
    expected = (str(plan.db_target), plan.volume_target, str(plan.archive_target))
    if supplied != expected:
        raise DemoToolError(
            "Restore refused: all three confirmations must exactly match the printed targets."
        )
    if api_stopped is None:
        _check_api_stopped()
    elif not api_stopped:
        raise DemoToolError("Restore refused: API is running; stop it before restore.")

    if not plan.db_target.is_file():
        raise DemoToolError(f"Restore target DB does not exist: {plan.db_target}")
    image_from_compose = _pinned_image()
    if image_from_compose != plan.image_digest:
        raise DemoToolError(
            "Restore refused: snapshot image digest differs from docker-compose.yml."
        )
    volumes = json.loads(
        runner(["docker", "volume", "inspect", plan.volume_target], REPO_ROOT).stdout
    )
    if len(volumes) != 1 or volumes[0].get("Name") != plan.volume_target:
        raise DemoToolError(
            "Restore refused: the confirmed Hindsight volume does not exist exactly as named."
        )

    stopped = False
    try:
        runner(["docker", "compose", "stop", "hindsight"], REPO_ROOT)
        stopped = True
        with sqlite3.connect(f"file:{plan.snapshot_db}?mode=ro", uri=True) as source:
            with sqlite3.connect(plan.db_target) as destination:
                source.backup(destination)
        runner(
            [
                "docker", "run", "--rm", "--pull=never",
                "--mount", f"type=volume,src={plan.volume_target},dst=/snapshot",
                "--mount", f"type=bind,src={plan.archive_target.parent},dst=/backup,readonly",
                "--entrypoint", "sh", plan.image_digest, "-c",
                "find /snapshot -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && "
                "tar -xzf /backup/hindsight-data.tar.gz -C /snapshot --no-same-owner",
            ],
            REPO_ROOT,
        )
    finally:
        if stopped:
            runner(["docker", "compose", "start", "hindsight"], REPO_ROOT)
            _wait_healthy()
    print("Restore completed for the explicitly confirmed targets.")
    return True


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="demo-tools")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    snapshot = subparsers.add_parser("snapshot")
    snapshot.add_argument("--name", required=True)
    restore = subparsers.add_parser("restore")
    restore.add_argument("--name", required=True)
    restore.add_argument("--confirm-db")
    restore.add_argument("--confirm-volume")
    restore.add_argument("--confirm-snapshot")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.operation == "snapshot":
            run_snapshot(args.name)
        else:
            plan = build_restore_plan(args.name)
            restore_confirmed(
                plan,
                confirm_db=args.confirm_db,
                confirm_volume=args.confirm_volume,
                confirm_snapshot=args.confirm_snapshot,
            )
    except DemoToolError as exc:
        print(f"Refused: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
