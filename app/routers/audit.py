"""Admin-only audit log listing endpoint."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth_deps import require_roles
from app.crud.audit import ENTITY_TYPES, list_audit_logs
from app.database import get_db
from app.errors import ValidationAppError
from app.schemas import AuditLogOut, PaginatedResponse

router = APIRouter(prefix="/audit", tags=["audit"])

_DEFAULT_PAGE_SIZE = 20
_MAX_PAGE_SIZE = 100


@router.get("", response_model=PaginatedResponse[AuditLogOut])
def list_audit(
    entity_type: str | None = Query(default=None, alias="entityType"),
    entity_id: uuid.UUID | None = Query(default=None, alias="entityId"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=_DEFAULT_PAGE_SIZE, ge=1, le=_MAX_PAGE_SIZE, alias="pageSize"),
    db: Session = Depends(get_db),
    _current_user=Depends(require_roles("admin")),
) -> PaginatedResponse[AuditLogOut]:
    """List audit log rows, optionally filtered by entityType/entityId. Admin only."""
    if entity_type is not None and entity_type not in ENTITY_TYPES:
        raise ValidationAppError(f"entityType must be one of {', '.join(ENTITY_TYPES)}")

    items, total = list_audit_logs(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        page=page,
        page_size=page_size,
    )
    return PaginatedResponse[AuditLogOut](
        items=[AuditLogOut.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )
