"""Shared pytest fixtures: a throwaway Postgres/Redis-backed TestClient.

DATABASE_URL/REDIS_URL point at a scratch database/Redis logical DB (index 1)
so running this suite never touches real data. No manual migrations are
needed: `init_db()` (already called on app startup) creates the schema.
"""
from __future__ import annotations

import os
import uuid

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://helpdesk:helpdesk@localhost:5432/helpdesk_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("JWT_SECRET", "test-secret-do-not-use-in-prod")
os.environ.setdefault("CORS_ORIGINS", "*")
os.environ.pop("ADMIN_EMAIL", None)
os.environ.pop("ADMIN_PASSWORD", None)

import pytest
import redis as redis_lib
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.crud.users import create_user
from app.database import SessionLocal, engine
from app.main import app
from app.redis_client import get_redis_pool


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _clean_state(client):
    """Reset DB rows + Redis before every test so each test starts isolated."""
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE audit_logs, comments, tickets, users RESTART IDENTITY CASCADE"))
        conn.execute(text("ALTER SEQUENCE IF EXISTS ticket_number_seq RESTART WITH 1"))
    redis_client = redis_lib.Redis(connection_pool=get_redis_pool())
    redis_client.flushdb()
    yield


def make_user(
    email: str | None = None,
    password: str = "Passw0rd1!",
    role: str = "customer",
    is_active: bool = True,
    full_name: str | None = None,
) -> dict:
    """Create a user directly in the DB (bypassing the API) for test setup."""
    email = email or f"{uuid.uuid4().hex}@example.com"
    full_name = full_name or email.split("@")[0]
    db = SessionLocal()
    try:
        user = create_user(
            db,
            full_name=full_name,
            email=email,
            password=password,
            role=role,
            is_active=is_active,
        )
        db.commit()
        return {"id": str(user.id), "email": email, "password": password, "role": role, "fullName": full_name}
    finally:
        db.close()


def login(client: TestClient, email: str, password: str) -> dict:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
