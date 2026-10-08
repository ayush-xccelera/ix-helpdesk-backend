"""Authentication endpoints: register, login, refresh, logout, me.

Self-service registration always creates a ``customer`` account; admins and
agents are provisioned through the admin-only users router instead.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from redis import Redis
from sqlalchemy.orm import Session

from app.auth_deps import get_current_user
from app.config import settings
from app.crud.users import authenticate_user, create_user, get_user_by_id
from app.database import get_db
from app.errors import UnauthorizedError
from app.models import User
from app.redis_client import get_redis
from app.redis_rate_limit import enforce_rate_limit
from app.refresh_tokens import issue_refresh_token, revoke_refresh_token, rotate_refresh_token
from app.schemas import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RefreshResponse,
    RegisterRequest,
    TokenResponse,
    UserOut,
)
from app.security import create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _issue_token_response(db: Session, redis_client: Redis, user: User) -> TokenResponse:
    access_token, expires_in = create_access_token(user.id, user.role)
    refresh_token = issue_refresh_token(redis_client, user.id)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        user=UserOut.model_validate(user),
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
) -> UserOut:
    """Create a new self-service customer account. Role/isActive are never client-controlled."""
    user = create_user(
        db,
        full_name=payload.full_name,
        email=payload.email,
        password=payload.password,
        role="customer",
        is_active=True,
    )
    return UserOut.model_validate(user)


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
    redis_client: Redis = Depends(get_redis),
) -> TokenResponse:
    """Authenticate with email/password, rate-limited per client IP."""
    rate_limit_key = f"ratelimit:login:{_client_ip(request)}"
    enforce_rate_limit(redis_client, rate_limit_key, settings.LOGIN_RATE_LIMIT_PER_MINUTE)

    user = authenticate_user(db, payload.email, payload.password)
    if user is None:
        raise UnauthorizedError("Invalid email or password")

    return _issue_token_response(db, redis_client, user)


@router.post("/refresh", response_model=RefreshResponse)
def refresh(
    payload: RefreshRequest,
    db: Session = Depends(get_db),
    redis_client: Redis = Depends(get_redis),
) -> RefreshResponse:
    """Rotate a single-use refresh token for a fresh access/refresh pair."""
    new_refresh_token, user_id = rotate_refresh_token(redis_client, payload.refresh_token)

    user = get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        revoke_refresh_token(redis_client, new_refresh_token)
        raise UnauthorizedError("User no longer exists or is inactive")

    access_token, _ = create_access_token(user.id, user.role)
    return RefreshResponse(access_token=access_token, refresh_token=new_refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def logout(
    payload: LogoutRequest,
    redis_client: Redis = Depends(get_redis),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Revoke a refresh token immediately; access tokens simply expire naturally."""
    revoke_refresh_token(redis_client, payload.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)) -> UserOut:
    """Return the authenticated user's own profile."""
    return UserOut.model_validate(current_user)
