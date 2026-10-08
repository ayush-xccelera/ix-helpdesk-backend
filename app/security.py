"""Password hashing and JWT access-token creation/verification."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.config import settings
from app.errors import UnauthorizedError

logger = logging.getLogger("app.security")

JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt."""
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Check a plaintext password against a stored bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        logger.warning("encountered malformed password hash during verification")
        return False


def create_access_token(user_id: uuid.UUID, role: str) -> tuple[str, int]:
    """Create a short-lived JWT access token. Returns (token, expires_in_seconds)."""
    expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token, expires_in


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT access token, raising UnauthorizedError on failure."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Access token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("Invalid access token") from exc

    if payload.get("type") != "access":
        raise UnauthorizedError("Invalid access token")
    return payload
