"""User management endpoints: list/get/create/patch, admin-centric RBAC."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth_deps import require_roles
from app.crud.users import create_user, get_user_by_id, list_users, update_user
from app.database import get_db
from app.errors import ForbiddenError, NotFoundError
from app.models import User
from app.schemas import (
    AdminUserCreateRequest,
    PaginatedResponse,
    UserOut,
    UserUpdateRequest,
)

router = APIRouter(prefix="/users", tags=["users"])

# Admins manage the user base; agents may browse/search it (e.g. to pick a
# ticket assignee) but cannot create or modify accounts. Customers have no
# access to this router at all.
_VIEW_ROLES = ("admin", "agent")
_MANAGE_ROLES = ("admin",)


@router.get("", response_model=PaginatedResponse[UserOut])
def list_users_endpoint(
    role: str | None = Query(default=None, pattern="^(admin|agent|customer)$"),
    q: str | None = Query(default=None, min_length=1, max_length=255),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*_VIEW_ROLES)),
) -> PaginatedResponse[UserOut]:
    # Agents may only use this endpoint to find assignable agents — never to
    # browse other roles or the whole user base. Admins are unrestricted.
    if current_user.role == "agent" and role != "agent":
        raise ForbiddenError("Agents may only list users filtered by role=agent")

    items, total = list_users(db, role=role, q=q, page=page, page_size=page_size)
    return PaginatedResponse[UserOut](
        items=[UserOut.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{user_id}", response_model=UserOut)
def get_user_endpoint(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*_VIEW_ROLES)),
) -> UserOut:
    user = get_user_by_id(db, user_id)
    if user is None:
        raise NotFoundError("User not found")
    return UserOut.model_validate(user)


@router.post("", response_model=UserOut, status_code=201)
def create_user_endpoint(
    payload: AdminUserCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*_MANAGE_ROLES)),
) -> UserOut:
    user = create_user(
        db,
        full_name=payload.full_name,
        email=payload.email,
        password=payload.password,
        role=payload.role,
        is_active=True,
        actor_id=current_user.id,
    )
    db.flush()
    return UserOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserOut)
def patch_user_endpoint(
    user_id: uuid.UUID,
    payload: UserUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*_MANAGE_ROLES)),
) -> UserOut:
    user = update_user(
        db,
        user_id=user_id,
        actor=current_user,
        full_name=payload.full_name,
        role=payload.role,
        is_active=payload.is_active,
    )
    return UserOut.model_validate(user)
