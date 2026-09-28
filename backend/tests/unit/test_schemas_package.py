"""`app.schemas` imports cleanly and re-exports every model (T05 done-when)."""

from __future__ import annotations

import app.schemas as schemas


def test_schemas_package_exports_every_public_name() -> None:
    for name in schemas.__all__:
        assert hasattr(schemas, name), f"app.schemas missing export {name!r}"
