"""FastAPI dependencies for authentication and role-based access control."""
from __future__ import annotations

from collections.abc import Callable, Iterable

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.crud.users import get_user_by_id
from app.database import get_db
from app.errors import ForbiddenError, UnauthorizedError
from app.models import User
from app.security import decode_access_token

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the current authenticated, active user from the Bearer access token."""
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("Missing bearer token")

    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("sub")
    user = get_user_by_id(db, user_id) if user_id else None
    if user is None:
        raise UnauthorizedError("User no longer exists")
    if not user.is_active:
        raise UnauthorizedError("User account is inactive")
    return user


def require_roles(*allowed_roles: str) -> Callable[[User], User]:
    """Build a dependency that only admits users whose role is in `allowed_roles`."""

    def _dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise ForbiddenError("You do not have permission to perform this action")
        return current_user

    return _dependency


def ensure_role(current_user: User, allowed_roles: Iterable[str]) -> None:
    """Imperative RBAC check for use inside service/CRUD logic with finer-grained rules."""
    if current_user.role not in allowed_roles:
        raise ForbiddenError("You do not have permission to perform this action")
