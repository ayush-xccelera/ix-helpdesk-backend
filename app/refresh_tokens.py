"""Opaque, single-use refresh-token storage and rotation, backed by Redis."""
from __future__ import annotations

import logging
import secrets
import uuid

import redis

from app.config import settings
from app.errors import UnauthorizedError

logger = logging.getLogger("app.refresh_tokens")

_KEY_PREFIX = "refresh:"
_TTL_SECONDS = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60


def _key(token: str) -> str:
    return f"{_KEY_PREFIX}{token}"


def issue_refresh_token(client: redis.Redis, user_id: uuid.UUID) -> str:
    """Create and persist a brand-new refresh token for the given user."""
    token = secrets.token_urlsafe(32)
    client.set(_key(token), str(user_id), ex=_TTL_SECONDS)
    return token


def rotate_refresh_token(client: redis.Redis, old_token: str) -> tuple[str, uuid.UUID]:
    """Validate + invalidate `old_token`, issue a fresh one. Raises UnauthorizedError if invalid/reused."""
    user_id_raw = client.getdel(_key(old_token))
    if user_id_raw is None:
        logger.info("refresh token reuse or invalid token rejected")
        raise UnauthorizedError("Invalid or already-used refresh token")

    user_id = uuid.UUID(user_id_raw)
    new_token = issue_refresh_token(client, user_id)
    return new_token, user_id


def revoke_refresh_token(client: redis.Redis, token: str) -> None:
    """Revoke a refresh token immediately (used on logout)."""
    client.delete(_key(token))
