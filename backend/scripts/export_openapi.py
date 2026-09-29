"""Write FastAPI OpenAPI without loading repository `.env` settings."""

from __future__ import annotations

import json
import sys
from typing import Any

from pydantic_settings import BaseSettings

_base_settings_init = BaseSettings.__init__


def _init_without_dotenv(self: Any, *args: Any, **kwargs: Any) -> None:
    kwargs["_env_file"] = None
    _base_settings_init(self, *args, **kwargs)


BaseSettings.__init__ = _init_without_dotenv  # type: ignore[method-assign]

from app.main import app  # noqa: E402

json.dump(app.openapi(), sys.stdout)
