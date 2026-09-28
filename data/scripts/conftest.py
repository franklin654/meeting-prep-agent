"""Make backend/ (app, tests.fakes) and data/scripts importable for the DATA-lane tests."""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parent.parent / "backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
