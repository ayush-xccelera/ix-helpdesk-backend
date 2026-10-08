"""FastAPI application assembly: startup bootstrap, CORS, routers, global error handling."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.crud.users import create_user, get_user_by_email
from app.database import SessionLocal, init_db
from app.errors import ApiError
from app.logging_middleware import RequestLoggingMiddleware
from app.routers import audit, auth, dashboard, health, tickets, users

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Create the schema idempotently and bootstrap the optional admin user on startup."""
    init_db()

    if settings.ADMIN_EMAIL and settings.ADMIN_PASSWORD:
        db = SessionLocal()
        try:
            existing = get_user_by_email(db, settings.ADMIN_EMAIL)
            if existing is None:
                create_user(
                    db,
                    full_name="Administrator",
                    email=settings.ADMIN_EMAIL,
                    password=settings.ADMIN_PASSWORD,
                    role="admin",
                    is_active=True,
                )
                db.commit()
                logger.info("bootstrap admin user created")
        except Exception:
            db.rollback()
            logger.exception("failed to bootstrap admin user")
            raise
        finally:
            db.close()

    yield


app = FastAPI(title="IT Helpdesk / Ticketing API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)


def _error_response(request: Request, status_code: int, code: str, message: str, details=None) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    logger.error(
        "request_id=%s status=%s code=%s message=%s",
        request_id,
        status_code,
        code,
        message,
    )
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details}},
    )


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return _error_response(request, exc.status_code, exc.code, exc.message, exc.details)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _error_response(request, 422, "VALIDATION_ERROR", "Request validation failed", details=exc.errors())


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return _error_response(request, exc.status_code, "HTTP_ERROR", str(exc.detail))


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    logger.exception("unhandled exception request_id=%s", request_id)
    return _error_response(request, 500, "INTERNAL_ERROR", "An unexpected error occurred")


app.include_router(health.router)
app.include_router(auth.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(tickets.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
