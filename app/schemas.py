"""Pydantic request/response DTOs. All wire fields are camelCase."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pydantic.alias_generators import to_camel

T = TypeVar("T")


class CamelModel(BaseModel):
    """Base DTO: snake_case Python attributes <-> camelCase wire fields."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


# ---------------------------------------------------------------------------
# Users / auth
# ---------------------------------------------------------------------------


class RegisterRequest(CamelModel):
    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class AdminUserCreateRequest(CamelModel):
    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(pattern="^(admin|agent|customer)$")


class UserUpdateRequest(CamelModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    role: str | None = Field(default=None, pattern="^(admin|agent|customer)$")
    is_active: bool | None = None


class UserOut(CamelModel):
    id: uuid.UUID
    full_name: str
    email: str
    role: str
    is_active: bool


class LoginRequest(CamelModel):
    email: EmailStr
    password: str


class RefreshRequest(CamelModel):
    refresh_token: str


class LogoutRequest(CamelModel):
    refresh_token: str


class TokenResponse(CamelModel):
    access_token: str
    refresh_token: str
    expires_in: int
    user: UserOut


class RefreshResponse(CamelModel):
    access_token: str
    refresh_token: str


class PaginatedResponse(CamelModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------

VALID_PRIORITIES = ("low", "medium", "high", "urgent")
VALID_CATEGORIES = ("hardware", "software", "network", "access", "other")
VALID_STATUSES = ("open", "in_progress", "resolved", "closed")


class TicketCreateRequest(CamelModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1)
    priority: str = Field(pattern="^(low|medium|high|urgent)$")
    category: str = Field(pattern="^(hardware|software|network|access|other)$")


class TicketUpdateRequest(CamelModel):
    status: str | None = Field(default=None, pattern="^(open|in_progress|resolved|closed)$")
    priority: str | None = Field(default=None, pattern="^(low|medium|high|urgent)$")
    assignee_id: uuid.UUID | None = None
    title: str | None = Field(default=None, max_length=120)
    description: str | None = None


class TicketOut(CamelModel):
    id: uuid.UUID
    number: str
    title: str
    description: str
    priority: str
    category: str
    status: str
    requester_id: uuid.UUID
    assignee_id: uuid.UUID | None
    sla_due_at: datetime
    sla_breached: bool
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CommentCreateRequest(CamelModel):
    body: str = Field(min_length=1)
    internal: bool = False


class CommentOut(CamelModel):
    id: uuid.UUID
    ticket_id: uuid.UUID
    author_id: uuid.UUID
    body: str
    internal: bool
    created_at: datetime


class ActorOut(CamelModel):
    id: uuid.UUID
    full_name: str


class HistoryOut(CamelModel):
    id: uuid.UUID
    action: str
    actor: ActorOut
    created_at: datetime
    changes: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Dashboard / audit
# ---------------------------------------------------------------------------


class DailyCount(CamelModel):
    date: str
    count: int


class DashboardSummary(CamelModel):
    total_open: int
    by_status: dict[str, int]
    by_priority: dict[str, int]
    sla_breached: int
    avg_resolution_hours: float | None
    created_last7_days: list[DailyCount]


class AuditLogOut(CamelModel):
    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    action: str
    actor_id: uuid.UUID
    changes: dict[str, Any] | None = None
    created_at: datetime
