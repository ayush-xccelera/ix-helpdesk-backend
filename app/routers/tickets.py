"""Ticket endpoints: create/list/get/patch, plus nested comments and history."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth_deps import get_current_user
from app.crud.audit import list_ticket_history
from app.crud.comments import add_comment, list_comments
from app.crud.tickets import (
    create_ticket,
    ensure_can_view_ticket,
    get_ticket,
    is_sla_breached,
    list_tickets,
    update_ticket,
)
from app.database import get_db
from app.models import Ticket, User
from app.schemas import (
    VALID_CATEGORIES,
    VALID_PRIORITIES,
    VALID_STATUSES,
    CommentCreateRequest,
    CommentOut,
    HistoryOut,
    PaginatedResponse,
    TicketCreateRequest,
    TicketOut,
    TicketUpdateRequest,
)

router = APIRouter(prefix="/tickets", tags=["tickets"])


def _ticket_to_out(ticket: Ticket) -> TicketOut:
    return TicketOut(
        id=ticket.id,
        number=ticket.number,
        title=ticket.title,
        description=ticket.description,
        priority=ticket.priority,
        category=ticket.category,
        status=ticket.status,
        requester_id=ticket.requester_id,
        assignee_id=ticket.assignee_id,
        sla_due_at=ticket.sla_due_at,
        sla_breached=is_sla_breached(ticket),
        resolved_at=ticket.resolved_at,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


@router.post("", response_model=TicketOut, status_code=201)
def create_ticket_endpoint(
    payload: TicketCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketOut:
    ticket = create_ticket(
        db,
        requester=current_user,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        category=payload.category,
    )
    return _ticket_to_out(ticket)


@router.get("", response_model=PaginatedResponse[TicketOut])
def list_tickets_endpoint(
    status: str | None = Query(default=None, pattern="^(" + "|".join(VALID_STATUSES) + ")$"),
    priority: str | None = Query(default=None, pattern="^(" + "|".join(VALID_PRIORITIES) + ")$"),
    category: str | None = Query(default=None, pattern="^(" + "|".join(VALID_CATEGORIES) + ")$"),
    assignee_id: uuid.UUID | None = Query(default=None, alias="assigneeId"),
    requester_id: uuid.UUID | None = Query(default=None, alias="requesterId"),
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize"),
    sort: str = Query(default="createdAt:desc"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[TicketOut]:
    page_size = min(page_size, 100)
    items, total = list_tickets(
        db,
        viewer=current_user,
        status=status,
        priority=priority,
        category=category,
        assignee_id=assignee_id,
        requester_id=requester_id,
        q=q,
        page=page,
        page_size=page_size,
        sort=sort,
    )
    return PaginatedResponse[TicketOut](
        items=[_ticket_to_out(t) for t in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{ticket_id}", response_model=TicketOut)
def get_ticket_endpoint(
    ticket_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketOut:
    ticket = get_ticket(db, ticket_id)
    ensure_can_view_ticket(ticket, current_user)
    return _ticket_to_out(ticket)


@router.patch("/{ticket_id}", response_model=TicketOut)
def update_ticket_endpoint(
    ticket_id: uuid.UUID,
    payload: TicketUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketOut:
    ticket = update_ticket(
        db,
        ticket_id=ticket_id,
        actor=current_user,
        status=payload.status,
        priority=payload.priority,
        assignee_id=payload.assignee_id,
        title=payload.title,
        description=payload.description,
    )
    return _ticket_to_out(ticket)


@router.post("/{ticket_id}/comments", response_model=CommentOut, status_code=201)
def create_comment_endpoint(
    ticket_id: uuid.UUID,
    payload: CommentCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CommentOut:
    ticket = get_ticket(db, ticket_id)
    ensure_can_view_ticket(ticket, current_user)
    comment = add_comment(
        db,
        ticket=ticket,
        author=current_user,
        body=payload.body,
        internal=payload.internal,
    )
    return CommentOut.model_validate(comment)


@router.get("/{ticket_id}/comments", response_model=list[CommentOut])
def list_comments_endpoint(
    ticket_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[CommentOut]:
    ticket = get_ticket(db, ticket_id)
    ensure_can_view_ticket(ticket, current_user)
    comments = list_comments(db, ticket_id=ticket_id, viewer=current_user)
    return [CommentOut.model_validate(c) for c in comments]


@router.get("/{ticket_id}/history", response_model=list[HistoryOut])
def ticket_history_endpoint(
    ticket_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[HistoryOut]:
    ticket = get_ticket(db, ticket_id)
    ensure_can_view_ticket(ticket, current_user)
    entries = list_ticket_history(db, ticket_id)
    return [
        HistoryOut(
            id=entry.id,
            action=entry.action,
            actor={"id": entry.actor.id, "full_name": entry.actor.full_name},
            created_at=entry.created_at,
            changes=entry.changes,
        )
        for entry in entries
    ]
