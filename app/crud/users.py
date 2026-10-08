"""User data-access + business rules: creation, authentication, listing, admin updates.

Shared foundation module — consumed by both the auth feature (register/login)
and the user-management feature (list/create/patch). Function signatures here
are a fixed contract; routers must not duplicate this logic inline.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.crud.audit import write_audit_log
from app.errors import NotFoundError, SelfModificationForbiddenError, UniqueViolationError
from app.models import User
from app.security import hash_password, verify_password

VALID_ROLES = ("admin", "agent", "customer")


def get_user_by_id(db: Session, user_id: uuid.UUID | str) -> User | None:
    if isinstance(user_id, str):
        try:
            user_id = uuid.UUID(user_id)
        except ValueError:
            return None
    return db.get(User, user_id)


def get_user_by_email(db: Session, email: str) -> User | None:
    normalized = email.strip().lower()
    stmt = select(User).where(func.lower(User.email) == normalized)
    return db.scalars(stmt).first()


def create_user(
    db: Session,
    *,
    full_name: str,
    email: str,
    password: str,
    role: str = "customer",
    is_active: bool = True,
    actor_id: uuid.UUID | None = None,
) -> User:
    """Create a new user. Raises UniqueViolationError if the (case-insensitive) email exists."""
    normalized_email = email.strip().lower()
    if get_user_by_email(db, normalized_email) is not None:
        raise UniqueViolationError("A user with this email already exists")

    user = User(
        full_name=full_name,
        email=normalized_email,
        password_hash=hash_password(password),
        role=role,
        is_active=is_active,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise UniqueViolationError("A user with this email already exists") from exc

    write_audit_log(
        db,
        entity_type="user",
        entity_id=user.id,
        action="created",
        actor_id=actor_id or user.id,
        changes=None,
    )
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    """Return the user if email/password/active-status all check out, else None."""
    user = get_user_by_email(db, email)
    if user is None or not verify_password(password, user.password_hash):
        return None
    if not user.is_active:
        return None
    return user


def list_users(
    db: Session,
    *,
    role: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[User], int]:
    stmt = select(User)
    count_stmt = select(func.count()).select_from(User)

    if role:
        stmt = stmt.where(User.role == role)
        count_stmt = count_stmt.where(User.role == role)
    if q:
        pattern = f"%{q.strip().lower()}%"
        search_clause = or_(func.lower(User.full_name).like(pattern), func.lower(User.email).like(pattern))
        stmt = stmt.where(search_clause)
        count_stmt = count_stmt.where(search_clause)

    total = db.scalar(count_stmt) or 0
    stmt = stmt.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    items = list(db.scalars(stmt).all())
    return items, total


def update_user(
    db: Session,
    *,
    user_id: uuid.UUID,
    actor: User,
    full_name: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
) -> User:
    """Admin-only update of another (or the same) user's profile/role/active flag.

    Raises SelfModificationForbiddenError if the admin tries to demote or
    deactivate themselves.
    """
    is_self = actor.id == user_id
    if is_self and role is not None and role != "admin":
        raise SelfModificationForbiddenError()
    if is_self and is_active is False:
        raise SelfModificationForbiddenError()

    user = get_user_by_id(db, user_id)
    if user is None:
        raise NotFoundError("User not found")

    changes: dict[str, Any] = {}

    if full_name is not None and full_name != user.full_name:
        changes["fullName"] = {"before": user.full_name, "after": full_name}
        user.full_name = full_name
    if role is not None and role != user.role:
        changes["role"] = {"before": user.role, "after": role}
        user.role = role
    if is_active is not None and is_active != user.is_active:
        changes["isActive"] = {"before": user.is_active, "after": is_active}
        user.is_active = is_active

    db.flush()

    if changes:
        write_audit_log(
            db,
            entity_type="user",
            entity_id=user.id,
            action="updated",
            actor_id=actor.id,
            changes=changes,
        )
    return user
