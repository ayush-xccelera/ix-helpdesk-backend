"""Audit log writing and querying.

Every create/update of a ticket/user/comment must call `write_audit_log`.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog

ENTITY_TYPES = ("ticket", "user", "comment")
ACTIONS = ("created", "updated")


def write_audit_log(
    db: Session,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str,
    actor_id: uuid.UUID,
    changes: dict[str, Any] | None = None,
) -> AuditLog:
    """Persist one audit trail row. Caller is responsible for the surrounding commit."""
    entry = AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_id=actor_id,
        changes=changes,
    )
    db.add(entry)
    db.flush()
    return entry


def list_audit_logs(
    db: Session,
    *,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[AuditLog], int]:
    """Return a paginated, newest-first slice of audit logs matching the given filters."""
    stmt = select(AuditLog)
    count_stmt = select(func.count()).select_from(AuditLog)

    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
        count_stmt = count_stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
        count_stmt = count_stmt.where(AuditLog.entity_id == entity_id)

    total = db.scalar(count_stmt) or 0

    stmt = stmt.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    items = list(db.scalars(stmt).all())
    return items, total


def list_ticket_history(db: Session, ticket_id: uuid.UUID) -> list[AuditLog]:
    """Return every audit event for a single ticket, newest first."""
    stmt = (
        select(AuditLog)
        .where(AuditLog.entity_type == "ticket", AuditLog.entity_id == ticket_id)
        .order_by(AuditLog.created_at.desc())
    )
    return list(db.scalars(stmt).all())
