"""reset_demo (T11): confirmations, guards, dry run. tmp-path files and a fake memory only."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import reset_demo
from reset_demo import ResetPlan, perform_reset

from app.core.errors import MemoryUnavailableError
from tests.fakes.fake_memory_service import FakeMemoryService

BANK = "ae-priya"


class CountingMemory(FakeMemoryService):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    async def delete_bank(self, bank_id: str) -> None:
        self.calls.append(f"delete_bank:{bank_id}")
        await super().delete_bank(bank_id)

    async def ensure_bank(self) -> None:
        self.calls.append("ensure_bank")
        await super().ensure_bank()

    async def wait_until_idle(self, timeout_s: float = 60.0) -> bool:
        self.calls.append("wait_until_idle")
        return await super().wait_until_idle(timeout_s)


class Harness:
    def __init__(self, db: Path, bank: str = BANK) -> None:
        self.db = db
        self.bank = bank
        self.memory = CountingMemory()
        self.tables_created = 0
        self.seed_runs = 0
        self.out: list[str] = []
        self.seed_rc = 0

    def _tables(self) -> None:
        self.tables_created += 1
        self.db.write_bytes(b"fresh")

    async def _seed(self) -> int:
        self.seed_runs += 1
        return self.seed_rc

    def run(
        self,
        *,
        confirm_bank: str | None = None,
        confirm_db: str | None = None,
        dry_run: bool = False,
    ) -> int:
        plan = ResetPlan(db_path=self.db, bank_id=self.bank)
        return asyncio.run(
            perform_reset(
                plan,
                memory=self.memory,
                confirm_bank=confirm_bank,
                confirm_db=confirm_db,
                dry_run=dry_run,
                recreate_tables=self._tables,
                run_seed=self._seed,
                out=self.out.append,
            )
        )

    def untouched(self) -> bool:
        return self.memory.calls == [] and self.tables_created == 0 and self.seed_runs == 0


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "app.db"
    path.write_bytes(b"precious")
    return path


@pytest.fixture
def h(db: Path) -> Harness:
    return Harness(db)


def test_prints_abs_path_and_bank(h: Harness) -> None:
    h.run()
    text = "\n".join(h.out)
    assert str(h.db) in text and BANK in text


def test_refuses_without_confirmations(h: Harness) -> None:
    assert h.run() != 0
    assert h.db.read_bytes() == b"precious" and h.untouched()
    text = "\n".join(h.out)
    assert "--confirm-bank" in text and "--confirm-db" in text


@pytest.mark.parametrize("which", ["bank_only", "db_only"])
def test_refuses_with_only_one_confirmation(h: Harness, which: str) -> None:
    kwargs: dict[str, Any] = (
        {"confirm_bank": BANK} if which == "bank_only" else {"confirm_db": str(h.db)}
    )
    assert h.run(**kwargs) != 0
    assert h.db.read_bytes() == b"precious" and h.untouched()


def test_refuses_on_wrong_bank(h: Harness) -> None:
    assert h.run(confirm_bank="ae-other", confirm_db=str(h.db)) != 0
    assert h.db.exists() and h.untouched()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: str(p) + " ",
        lambda p: str(p.parent / "other.db"),
        lambda p: f"{p.parent}/./{p.name}",
        lambda p: p.name,
        lambda p: str(p) + "/",
    ],
)
def test_refuses_on_db_path_mismatch(h: Harness, mutate: Callable[[Path], str]) -> None:
    assert h.run(confirm_bank=BANK, confirm_db=mutate(h.db)) != 0
    assert h.db.read_bytes() == b"precious" and h.untouched()


def test_dry_run_touches_nothing(h: Harness) -> None:
    assert h.run(dry_run=True) == 0
    assert h.db.read_bytes() == b"precious"
    assert h.untouched()
    assert "dry" in "\n".join(h.out).lower()


def test_dry_run_with_confirmations_still_touches_nothing(h: Harness) -> None:
    assert h.run(confirm_bank=BANK, confirm_db=str(h.db), dry_run=True) == 0
    assert h.db.read_bytes() == b"precious" and h.untouched()


def test_dry_run_does_not_need_the_file(tmp_path: Path) -> None:
    hh = Harness(tmp_path / "missing.db")
    assert hh.run(dry_run=True) == 0 and hh.untouched()
    assert not hh.db.exists()


def test_confirmed_run_deletes_only_target_and_calls_delete_bank_once(
    h: Harness, tmp_path: Path
) -> None:
    neighbour = tmp_path / "other.db"
    neighbour.write_bytes(b"keep")
    backup = tmp_path / "app.db.bak"
    backup.write_bytes(b"keep")
    assert h.run(confirm_bank=BANK, confirm_db=str(h.db)) == 0
    assert [c for c in h.memory.calls if c.startswith("delete_bank")] == [f"delete_bank:{BANK}"]
    assert h.memory.deleted_banks == [BANK]
    assert neighbour.read_bytes() == b"keep" and backup.read_bytes() == b"keep"
    assert h.db.read_bytes() == b"fresh"  # the old file is gone, tables were recreated
    assert h.tables_created == 1 and h.seed_runs == 1
    assert h.memory.calls.index("ensure_bank") > h.memory.calls.index(f"delete_bank:{BANK}")


def test_confirmed_run_removes_wal_and_shm_siblings(h: Harness, tmp_path: Path) -> None:
    wal = tmp_path / "app.db-wal"
    shm = tmp_path / "app.db-shm"
    wal.write_bytes(b"w")
    shm.write_bytes(b"s")
    assert h.run(confirm_bank=BANK, confirm_db=str(h.db)) == 0
    assert not wal.exists() and not shm.exists()


def test_confirmed_run_with_absent_file_is_fine(tmp_path: Path) -> None:
    hh = Harness(tmp_path / "gone.db")
    assert hh.run(confirm_bank=BANK, confirm_db=str(hh.db)) == 0
    assert hh.memory.deleted_banks == [BANK]


def test_seed_failure_exit_code_is_propagated(h: Harness) -> None:
    h.seed_rc = 1
    assert h.run(confirm_bank=BANK, confirm_db=str(h.db)) == 1


@pytest.mark.parametrize("bad", ["ami-test", "spike-x", "ae-", "AE-priya", "ae-a b"])
def test_refuses_bad_bank_ids_even_when_confirmed(db: Path, bad: str) -> None:
    hh = Harness(db, bank=bad)
    assert hh.run(confirm_bank=bad, confirm_db=str(db)) != 0
    assert db.read_bytes() == b"precious" and hh.untouched()


@pytest.mark.parametrize("name", ["app.txt", "app", "data.sqlite3x", "app.db.bak"])
def test_refuses_files_without_db_suffix(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_bytes(b"precious")
    hh = Harness(path)
    assert hh.run(confirm_bank=BANK, confirm_db=str(path)) != 0
    assert path.read_bytes() == b"precious" and hh.untouched()


def test_accepts_sqlite_suffix(tmp_path: Path) -> None:
    path = tmp_path / "demo.sqlite"
    path.write_bytes(b"x")
    hh = Harness(path)
    assert hh.run(confirm_bank=BANK, confirm_db=str(path)) == 0


def test_refuses_directory_and_symlink(tmp_path: Path) -> None:
    directory = tmp_path / "dir.db"
    directory.mkdir()
    hh = Harness(directory)
    assert hh.run(confirm_bank=BANK, confirm_db=str(directory)) != 0
    assert directory.is_dir() and hh.untouched()

    real = tmp_path / "real.db"
    real.write_bytes(b"precious")
    link = tmp_path / "link.db"
    link.symlink_to(real)
    hl = Harness(link)
    assert hl.run(confirm_bank=BANK, confirm_db=str(link)) != 0
    assert real.read_bytes() == b"precious" and hl.untouched()


def test_bank_delete_failure_leaves_the_db_file(h: Harness) -> None:
    async def boom(bank_id: str) -> None:
        raise MemoryUnavailableError("down")

    h.memory.delete_bank = boom  # type: ignore[method-assign]
    with pytest.raises(MemoryUnavailableError):
        h.run(confirm_bank=BANK, confirm_db=str(h.db))
    assert h.db.read_bytes() == b"precious" and h.seed_runs == 0


def test_warns_about_running_api(h: Harness) -> None:
    h.run(confirm_bank=BANK, confirm_db=str(h.db))
    text = "\n".join(h.out).lower()
    assert "stop" in text and "api" in text


def test_module_imports_without_side_effects() -> None:
    assert callable(reset_demo.main)
