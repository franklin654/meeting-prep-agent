"""Account and contact creation/listing endpoints."""

from __future__ import annotations

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import get_session
from app.db import entities_repo, repository
from app.schemas.api import (
    AccountCreate,
    AccountResponse,
    ContactConfirmRequest,
    ContactCreate,
    ContactSummary,
)

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/accounts", response_model=AccountResponse)
def post_account(body: AccountCreate, session: SessionDep) -> AccountResponse:
    row = entities_repo.create_account(
        session, name=body.name, industry=body.industry or "", stage=body.stage
    )
    return AccountResponse(
        id=row.id,
        name=row.name,
        industry=row.industry,
        stage=cast(Literal["discovery", "evaluation", "closed_won", "closed_lost"], row.stage),
    )


@router.get("/accounts", response_model=list[AccountResponse])
def get_accounts(session: SessionDep) -> list[AccountResponse]:
    return [
        AccountResponse(
            id=a.id,
            name=a.name,
            industry=a.industry,
            stage=cast(Literal["discovery", "evaluation", "closed_won", "closed_lost"], a.stage),
        )
        for a in repository.list_accounts(session)
    ]


@router.post("/contacts", response_model=ContactSummary)
def post_contact(body: ContactCreate, session: SessionDep) -> ContactSummary:
    row = entities_repo.create_contact(
        session, account_id=body.account_id, name=body.name, role=body.role, aliases=body.aliases
    )
    account = repository.get_account(session, body.account_id)
    assert account is not None
    return ContactSummary(
        id=row.id,
        name=row.name,
        role=row.role,
        account_id=row.account_id,
        account_name=account.name,
    )


@router.get("/contacts", response_model=list[ContactSummary])
def get_contacts(
    session: SessionDep,
    query: str | None = None,
    account_id: str | None = None,
    include_unconfirmed: bool = False,
) -> list[ContactSummary]:
    output: list[ContactSummary] = []
    for contact in entities_repo.list_contacts(session, query=query, account_id=account_id):
        if contact.account_id is None or (contact.needs_review and not include_unconfirmed):
            continue
        account = (
            repository.get_account(session, contact.account_id) if contact.account_id else None
        )
        meetings_count, open_followups, last_meeting_date = entities_repo.contact_metrics(
            session, contact.id
        )
        output.append(
            ContactSummary(
                id=contact.id,
                name=contact.name,
                role=contact.role,
                account_id=contact.account_id,
                account_name=account.name if account else None,
                meetings_count=meetings_count,
                open_followups=open_followups,
                last_meeting_date=last_meeting_date,
                needs_review=contact.needs_review,
            )
        )
    return output


@router.patch("/contacts/{contact_id}", response_model=ContactSummary)
def confirm_contact(
    contact_id: str, body: ContactConfirmRequest, session: SessionDep
) -> ContactSummary:
    contact = repository.update_contact(
        session, contact_id, name=body.name, role=body.role, needs_review=False
    )
    account = repository.get_account(session, contact.account_id) if contact.account_id else None
    meetings_count, open_followups, last_meeting_date = entities_repo.contact_metrics(
        session, contact.id
    )
    return ContactSummary(
        id=contact.id,
        name=contact.name,
        role=contact.role,
        account_id=contact.account_id,
        account_name=account.name if account else None,
        meetings_count=meetings_count,
        open_followups=open_followups,
        last_meeting_date=last_meeting_date,
        needs_review=contact.needs_review,
    )
