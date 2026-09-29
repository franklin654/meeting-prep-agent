"""Deterministic dashboard nudges (T26)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import get_session
from app.schemas.api import Nudge
from app.services.nudges import build_nudges

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/nudges", response_model=list[Nudge])
def list_nudges(session: SessionDep) -> list[Nudge]:
    return build_nudges(session)
