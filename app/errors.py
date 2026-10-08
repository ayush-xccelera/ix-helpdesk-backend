"""Domain-specific exception types and the shared error envelope they carry.

Routers/services raise these; the single global handler registered in
``app.main`` turns them (and any unhandled exception) into the standardized
``{"error": {"code", "message", "details"}}`` JSON envelope.
"""
from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """Base class for every error the API deliberately raises.

    Carries everything the global exception handler needs to build the
    response envelope, so no router/service ever hand-builds error JSON.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


class NotFoundError(ApiError):
    def __init__(self, message: str = "Resource not found", details: Any | None = None) -> None:
        super().__init__(404, "NOT_FOUND", message, details)


class ForbiddenError(ApiError):
    def __init__(self, message: str = "Forbidden", code: str = "FORBIDDEN", details: Any | None = None) -> None:
        super().__init__(403, code, message, details)


class UnauthorizedError(ApiError):
    def __init__(self, message: str = "Unauthorized", details: Any | None = None) -> None:
        super().__init__(401, "UNAUTHORIZED", message, details)


class ValidationAppError(ApiError):
    def __init__(self, message: str, code: str = "VALIDATION_ERROR", details: Any | None = None) -> None:
        super().__init__(422, code, message, details)


class ConflictError(ApiError):
    def __init__(self, message: str, code: str = "CONFLICT", details: Any | None = None) -> None:
        super().__init__(409, code, message, details)


class InvalidTransitionError(ConflictError):
    def __init__(self, message: str, details: Any | None = None) -> None:
        super().__init__(message, code="INVALID_TRANSITION", details=details)


class InvalidAssigneeError(ValidationAppError):
    def __init__(
        self,
        message: str = "assigneeId must reference an active agent or admin",
        details: Any | None = None,
    ) -> None:
        super().__init__(message, code="INVALID_ASSIGNEE", details=details)


class UniqueViolationError(ValidationAppError):
    def __init__(self, message: str = "A record with this value already exists", details: Any | None = None) -> None:
        super().__init__(message, code="UNIQUE_VIOLATION", details=details)


class SelfModificationForbiddenError(ForbiddenError):
    def __init__(self, message: str = "Admins cannot demote or deactivate themselves") -> None:
        super().__init__(message, code="SELF_MODIFICATION_FORBIDDEN")


class RateLimitError(ApiError):
    def __init__(self, message: str = "Too many requests, please try again later") -> None:
        super().__init__(429, "RATE_LIMITED", message)
