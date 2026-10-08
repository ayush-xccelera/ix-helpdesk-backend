"""Redis connection factory."""
from __future__ import annotations

from functools import lru_cache

import redis

from app.config import settings


@lru_cache
def get_redis_pool() -> redis.ConnectionPool:
    return redis.ConnectionPool.from_url(settings.REDIS_URL, decode_responses=True)


def get_redis() -> redis.Redis:
    """FastAPI dependency returning a Redis client bound to the shared pool."""
    return redis.Redis(connection_pool=get_redis_pool())
