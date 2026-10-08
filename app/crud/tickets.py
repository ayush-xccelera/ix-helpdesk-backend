"""Ticket data-access + business rules: numbering, SLA, listing, updates.

Consumed exclusively by ``app.routers.tickets``. All RBAC/visibility and
status-transition rules live here so the router stays a thin HTTP layer.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.crud.audit import write_audit_log
from app.crud.users import get_user_by_id
from app.database import TICKET_NUMBER_SEQUENCE
from app.errors import (
    ForbiddenError,
    InvalidAssigneeError,
    InvalidTransitionError,
    NotFoundError,
    ValidationAppError,
)
from app.models import Ticket, User

# Hours-to-breach per priority, counted from ticket creation.
SLA_HOURS_BY_PRIORITY: dict[str, int] = {
    "urgent": 4,
    "high": 8,
    "medium": 24,
    "low": 72,
}

# Allowed status transitions, per the functional spec:
#   open -> in_progress
#   in_progress -> resolved | open
#   resolved -> closed | open
#   closed -> (terminal for everyone except an admin, who may reopen it)
VALID_STATUS_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "open": ("in_progress",),
    "in_progress": ("resolved", "open"),
    "resolved": ("closed", "open"),
    "closed": (),
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _next_ticket_number(db: Session) -> str:
    seq_value = db.execute(text(f"SELECT nextval('{TICKET_NUMBER_SEQUENCE}')")).scalar_one()
    return f"HD-{seq_value:04d}"


def compute_sla_due_at(priority: str, created_at: datetime | None = None) -> datetime:
    base = created_at or _utcnow()
    hours = SLA_HOURS_BY_PRIORITY.get(priority, SLA_HOURS_BY_PRIORITY["medium"])
    return base + timedelta(hours=hours)


def is_sla_breached(ticket: Ticket) -> bool:
    """A ticket breaches SLA once the due time has passed without resolution."""
    deadline = ticket.sla_due_at
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if ticket.resolved_at is not None:
        resolved_at = ticket.resolved_at
        if resolved_at.tzinfo is None:
            resolved_at = resolved_at.replace(tzinfo=timezone.utc)
        return resolved_at > deadline
    return _utcnow() > deadline


def create_ticket(
    db: Session,
    *,
    requester: User,
    title: str,
    description: str,
    priority: str,
    category: str,
) -> Ticket:
    """File a new ticket on behalf of the authenticated requester."""
    now = _utcnow()
    ticket = Ticket(
        number=_next_ticket_number(db),
        title=title,
        description=description,
        priority=priority,
        category=category,
        status="open",
        requester_id=requester.id,
        assignee_id=None,
        sla_due_at=compute_sla_due_at(priority, now),
        created_at=now,
        updated_at=now,
    )
    db.add(ticket)
    db.flush()

    write_audit_log(
        db,
        entity_type="ticket",
        entity_id=ticket.id,
        action="created",
        actor_id=requester.id,
        changes=None,
    )
    return ticket


def get_ticket(db: Session, ticket_id: uuid.UUID) -> Ticket:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise NotFoundError("Ticket not found")
    return ticket


def ensure_can_view_ticket(ticket: Ticket, viewer: User) -> None:
    """Customers may only see their own tickets; agents/admins see everything."""
    if viewer.role == "customer" and ticket.requester_id != viewer.id:
        raise ForbiddenError("You do not have access to this ticket")


def list_tickets(
    db: Session,
    *,
    viewer: User,
    status: str | None = None,
    priority: str | None = None,
    category: str | None = None,
    assignee_id: uuid.UUID | None = None,
    requester_id: uuid.UUID | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
    sort: str = "createdAt:desc",
) -> tuple[list[Ticket], int]:
    page_size = min(page_size, 100)
    stmt = select(Ticket)
    count_stmt = select(func.count()).select_from(Ticket)

    # Visibility: a customer can only ever see tickets they filed.
    if viewer.role == "customer":
        stmt = stmt.where(Ticket.requester_id == viewer.id)
        count_stmt = count_stmt.where(Ticket.requester_id == viewer.id)
    elif requester_id is not None:
        stmt = stmt.where(Ticket.requester_id == requester_id)
        count_stmt = count_stmt.where(Ticket.requester_id == requester_id)

    if status:
        stmt = stmt.where(Ticket.status == status)
        count_stmt = count_stmt.where(Ticket.status == status)
    if priority:
        stmt = stmt.where(Ticket.priority == priority)
        count_stmt = count_stmt.where(Ticket.priority == priority)
    if category:
        stmt = stmt.where(Ticket.category == category)
        count_stmt = count_stmt.where(Ticket.category == category)
    if assignee_id is not None:
        stmt = stmt.where(Ticket.assignee_id == assignee_id)
        count_stmt = count_stmt.where(Ticket.assignee_id == assignee_id)
    if q:
        pattern = f"%{q.strip().lower()}%"
        search_clause = or_(
            func.lower(Ticket.title).like(pattern),
            func.lower(Ticket.description).like(pattern),
        )
        stmt = stmt.where(search_clause)
        count_stmt = count_stmt.where(search_clause)

    total = db.scalar(count_stmt) or 0

    # "createdAt" is the only sortable field the functional spec requires;
    # any other (or missing) sort field falls back to it rather than erroring.
    _sort_column, _, sort_direction = (sort or "createdAt:desc").partition(":")
    order_column = Ticket.created_at
    order_clause = order_column.asc() if sort_direction == "asc" else order_column.desc()

    stmt = stmt.order_by(order_clause).offset((page - 1) * page_size).limit(page_size)
    items = list(db.scalars(stmt).all())
    return items, total


def _validate_assignee(db: Session, assignee_id: uuid.UUID) -> User:
    assignee = get_user_by_id(db, assignee_id)
    if assignee is None or assignee.role not in ("agent", "admin") or not assignee.is_active:
        raise InvalidAssigneeError()
    return assignee


def update_ticket(
    db: Session,
    *,
    ticket_id: uuid.UUID,
    actor: User,
    status: str | None = None,
    priority: str | None = None,
    assignee_id: uuid.UUID | None = None,
    title: str | None = None,
    description: str | None = None,
) -> Ticket:
    """Apply a partial update to a ticket, enforcing RBAC and status-transition rules.

    - Customers may only edit the title/description of their own ticket, and
      only while it is still ``open``.
    - Agents/admins may change status, priority, assignee, title, description
      on any ticket.
    - Status changes must follow ``VALID_STATUS_TRANSITIONS``.
    - Resolving a ticket stamps ``resolved_at``; reopening clears it.
    """
    ticket = get_ticket(db, ticket_id)

    is_requester = ticket.requester_id == actor.id
    is_staff = actor.role in ("agent", "admin")

    if not is_staff:
        if not is_requester:
            raise ForbiddenError("You do not have access to this ticket")
        if status is not None or priority is not None or assignee_id is not None:
            raise ValidationAppError(
                "Customers may only edit title and description",
                code="CUSTOMER_FIELD_FORBIDDEN",
            )
        if ticket.status != "open":
            raise ValidationAppError(
                "Only open tickets can be edited by the requester",
                code="TICKET_NOT_EDITABLE",
            )

    changes: dict[str, Any] = {}

    if title is not None and title != ticket.title:
        changes["title"] = {"before": ticket.title, "after": title}
        ticket.title = title

    if description is not None and description != ticket.description:
        changes["description"] = {"before": ticket.description, "after": description}
        ticket.description = description

    if priority is not None and priority != ticket.priority:
        changes["priority"] = {"before": ticket.priority, "after": priority}
        ticket.priority = priority
        ticket.sla_due_at = compute_sla_due_at(priority, ticket.created_at)

    if assignee_id is not None and assignee_id != ticket.assignee_id:
        _validate_assignee(db, assignee_id)
        changes["assigneeId"] = {
            "before": str(ticket.assignee_id) if ticket.assignee_id else None,
            "after": str(assignee_id),
        }
        ticket.assignee_id = assignee_id

    if status is not None and status != ticket.status:
        allowed = set(VALID_STATUS_TRANSITIONS.get(ticket.status, ()))
        admin_reopen = ticket.status == "closed" and status == "open" and actor.role == "admin"
        if status not in allowed and not admin_reopen:
            raise InvalidTransitionError(
                f"Cannot transition ticket from '{ticket.status}' to '{status}'"
            )
        changes["status"] = {"before": ticket.status, "after": status}
        ticket.status = status
        if status == "resolved":
            ticket.resolved_at = _utcnow()
        elif status in ("open", "in_progress"):
            ticket.resolved_at = None

    db.flush()

    if changes:
        write_audit_log(
            db,
            entity_type="ticket",
            entity_id=ticket.id,
            action="updated",
            actor_id=actor.id,
            changes=changes,
        )

    return ticket
