"""Comment data-access + business rules for ticket conversations.

Consumed exclusively by ``app.routers.tickets``.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crud.audit import write_audit_log
from app.errors import ForbiddenError, NotFoundError
from app.models import Comment, Ticket, User


def add_comment(
    db: Session,
    *,
    ticket: Ticket,
    author: User,
    body: str,
    internal: bool = False,
) -> Comment:
    """Add a comment to a ticket.

    - The requester, the assignee, and any agent/admin may comment.
    - Internal (non-customer-visible) notes may only be authored by an
      agent or admin.
    """
    is_requester = ticket.requester_id == author.id
    is_assignee = ticket.assignee_id == author.id
    is_staff = author.role in ("agent", "admin")

    if not (is_requester or is_assignee or is_staff):
        raise NotFoundError("Ticket not found")

    if internal and not is_staff:
        raise ForbiddenError("Only agents or admins may post internal comments")

    comment = Comment(
        ticket_id=ticket.id,
        author_id=author.id,
        body=body,
        internal=internal,
    )
    db.add(comment)
    db.flush()

    write_audit_log(
        db,
        entity_type="comment",
        entity_id=comment.id,
        action="created",
        actor_id=author.id,
        changes={"ticketId": str(ticket.id), "internal": internal},
    )
    return comment


def list_comments(
    db: Session,
    *,
    ticket_id: uuid.UUID,
    viewer: User,
) -> list[Comment]:
    """Return every comment on a ticket, oldest first.

    Internal notes are stripped out for customers (requesters); agents,
    admins, and the assigned agent all see the full thread.
    """
    stmt = select(Comment).where(Comment.ticket_id == ticket_id).order_by(Comment.created_at.asc())
    comments = list(db.scalars(stmt).all())

    if viewer.role == "customer":
        comments = [c for c in comments if not c.internal]

    return comments
