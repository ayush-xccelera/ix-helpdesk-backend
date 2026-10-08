"""Fixed-window Redis-backed rate limiting (used for login attempts)."""
from __future__ import annotations

import logging

import redis

from app.errors import RateLimitError

logger = logging.getLogger("app.rate_limit")

WINDOW_SECONDS = 60


def enforce_rate_limit(client: redis.Redis, key: str, max_attempts: int) -> None:
    """Increment the fixed-window counter for `key`; raise RateLimitError past max_attempts."""
    count = client.incr(key)
    if count == 1:
        client.expire(key, WINDOW_SECONDS)
    if count > max_attempts:
        logger.warning("rate limit exceeded for key=%s count=%s", key, count)
        raise RateLimitError("Too many login attempts, please try again later")
