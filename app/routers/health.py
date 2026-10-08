"""Public health-check endpoints: live DB and Redis connectivity probes."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Response
from redis import Redis, RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.redis_client import get_redis

logger = logging.getLogger("app.health")

router = APIRouter(tags=["health"])


def _check_db(db: Session) -> str:
    try:
        db.execute(text("SELECT 1"))
        return "ok"
    except SQLAlchemyError:
        logger.exception("database health check failed")
        return "down"


def _check_redis(client: Redis) -> str:
    try:
        client.ping()
        return "ok"
    except RedisError:
        logger.exception("redis health check failed")
        return "down"


def _health_payload(response: Response, db: Session, redis_client: Redis) -> dict[str, str]:
    db_status = _check_db(db)
    redis_status = _check_redis(redis_client)
    overall_ok = db_status == "ok" and redis_status == "ok"
    response.status_code = 200 if overall_ok else 503
    return {"status": "ok" if overall_ok else "down", "db": db_status, "redis": redis_status}


@router.get("/health")
def health_root(
    response: Response,
    db: Session = Depends(get_db),
    redis_client: Redis = Depends(get_redis),
) -> dict[str, str]:
    return _health_payload(response, db, redis_client)


@router.get("/api/v1/health")
def health_v1(
    response: Response,
    db: Session = Depends(get_db),
    redis_client: Redis = Depends(get_redis),
) -> dict[str, str]:
    return _health_payload(response, db, redis_client)
