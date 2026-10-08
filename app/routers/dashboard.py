"""Dashboard summary endpoint: aggregated ticket statistics, Redis-cached.

Business/aggregation logic lives in the private helpers below (no dedicated
crud module was allocated for this feature); the route handler itself stays
thin, delegating to `_build_summary` and the Redis cache.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from redis import Redis, RedisError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth_deps import require_roles
from app.database import get_db
from app.models import Ticket
from app.redis_client import get_redis
from app.schemas import DashboardSummary

logger = logging.getLogger("app.dashboard")

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_CACHE_KEY = "dashboard:summary"
_CACHE_TTL_SECONDS = 60

_OPEN_STATUS = "open"
_TERMINAL_STATUSES = ("resolved", "closed")
_ALL_STATUSES = ("open", "in_progress", "resolved", "closed")
_ALL_PRIORITIES = ("low", "medium", "high", "urgent")


def _status_counts(db: Session) -> dict[str, int]:
    """Ticket count grouped by status, with every known status present (zero-filled)."""
    rows = db.execute(select(Ticket.status, func.count()).group_by(Ticket.status)).all()
    counts = {status: 0 for status in _ALL_STATUSES}
    for status, count in rows:
        counts[status] = count
    return counts


def _priority_counts(db: Session) -> dict[str, int]:
    """Ticket count grouped by priority, with every known priority present (zero-filled)."""
    rows = db.execute(select(Ticket.priority, func.count()).group_by(Ticket.priority)).all()
    counts = {priority: 0 for priority in _ALL_PRIORITIES}
    for priority, count in rows:
        counts[priority] = count
    return counts


def _sla_breached_count(db: Session, now: datetime) -> int:
    """Count tickets currently breaching SLA: overdue-and-open, or resolved/closed late."""
    overdue_open_stmt = (
        select(func.count())
        .select_from(Ticket)
        .where(Ticket.status.notin_(_TERMINAL_STATUSES), Ticket.sla_due_at < now)
    )
    late_resolved_stmt = (
        select(func.count())
        .select_from(Ticket)
        .where(
            Ticket.status.in_(_TERMINAL_STATUSES),
            Ticket.resolved_at.isnot(None),
            Ticket.resolved_at > Ticket.sla_due_at,
        )
    )
    overdue_open = db.scalar(overdue_open_stmt) or 0
    late_resolved = db.scalar(late_resolved_stmt) or 0
    return overdue_open + late_resolved


def _avg_resolution_hours(db: Session) -> float | None:
    """Average hours from createdAt to resolvedAt across every resolved ticket, or None."""
    avg_seconds = db.scalar(
        select(func.avg(func.extract("epoch", Ticket.resolved_at - Ticket.created_at))).where(
            Ticket.resolved_at.isnot(None)
        )
    )
    if avg_seconds is None:
        return None
    return round(float(avg_seconds) / 3600.0, 2)


def _created_last_7_days(db: Session, today: date) -> list[dict[str, object]]:
    """Daily ticket creation counts for the last 7 days (inclusive of today), zero-filled."""
    start = today - timedelta(days=6)
    day_expr = func.date(Ticket.created_at)
    rows = db.execute(
        select(day_expr.label("day"), func.count()).where(day_expr >= start).group_by(day_expr)
    ).all()

    by_day: dict[str, int] = {}
    for day_value, count in rows:
        key = day_value.isoformat() if hasattr(day_value, "isoformat") else str(day_value)
        by_day[key] = count

    return [
        {
            "date": (start + timedelta(days=offset)).isoformat(),
            "count": by_day.get((start + timedelta(days=offset)).isoformat(), 0),
        }
        for offset in range(7)
    ]


def _build_summary(db: Session) -> DashboardSummary:
    """Compute the full dashboard summary by querying the database directly (no cache)."""
    now = datetime.now(timezone.utc)
    by_status = _status_counts(db)
    by_priority = _priority_counts(db)
    return DashboardSummary(
        total_open=by_status.get(_OPEN_STATUS, 0),
        by_status=by_status,
        by_priority=by_priority,
        sla_breached=_sla_breached_count(db, now),
        avg_resolution_hours=_avg_resolution_hours(db),
        created_last7_days=_created_last_7_days(db, now.date()),
    )


@router.get("/summary", response_model=DashboardSummary)
def get_dashboard_summary(
    db: Session = Depends(get_db),
    redis_client: Redis = Depends(get_redis),
    _current_user=Depends(require_roles("admin", "agent")),
) -> DashboardSummary:
    """Return aggregated ticket statistics, served from a 60s Redis cache when available."""
    cached_payload: str | None = None
    try:
        cached_payload = redis_client.get(_CACHE_KEY)
    except RedisError:
        logger.exception("dashboard cache read failed; falling back to live computation")

    if cached_payload:
        return DashboardSummary.model_validate(json.loads(cached_payload))

    summary = _build_summary(db)

    try:
        redis_client.set(_CACHE_KEY, summary.model_dump_json(by_alias=True), ex=_CACHE_TTL_SECONDS)
    except RedisError:
        logger.exception("dashboard cache write failed; summary still returned uncached")

    return summary
