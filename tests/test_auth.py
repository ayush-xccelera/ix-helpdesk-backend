"""Auth flow tests: register, login, rate limiting, refresh rotation, logout."""
from __future__ import annotations

from tests.conftest import auth_header, login, make_user


def test_register_creates_customer(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"fullName": "New User", "email": "newuser@example.com", "password": "Passw0rd1!"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "newuser@example.com"
    assert body["role"] == "customer"
    assert body["isActive"] is True
    assert "password" not in body


def test_register_ignores_client_supplied_role(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "fullName": "Sneaky",
            "email": "sneaky@example.com",
            "password": "Passw0rd1!",
            "role": "admin",
            "isActive": False,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["role"] == "customer"
    assert body["isActive"] is True


def test_register_duplicate_email_case_insensitive(client):
    client.post(
        "/api/v1/auth/register",
        json={"fullName": "First", "email": "dup@example.com", "password": "Passw0rd1!"},
    )
    response = client.post(
        "/api/v1/auth/register",
        json={"fullName": "Second", "email": "DUP@example.com", "password": "Passw0rd1!"},
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "UNIQUE_VIOLATION"


def test_login_success_returns_tokens(client):
    make_user(email="login@example.com", password="Passw0rd1!", role="customer")
    response = client.post(
        "/api/v1/auth/login", json={"email": "login@example.com", "password": "Passw0rd1!"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "accessToken" in body
    assert "refreshToken" in body
    assert body["expiresIn"] == 15 * 60
    assert body["user"]["email"] == "login@example.com"


def test_login_wrong_password_generic_error(client):
    make_user(email="wrongpw@example.com", password="Passw0rd1!", role="customer")
    response = client.post(
        "/api/v1/auth/login", json={"email": "wrongpw@example.com", "password": "nope"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid email or password"


def test_login_nonexistent_email_same_generic_error(client):
    response = client.post(
        "/api/v1/auth/login", json={"email": "doesnotexist@example.com", "password": "whatever"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid email or password"


def test_login_inactive_user_rejected(client):
    make_user(email="inactive@example.com", password="Passw0rd1!", role="customer", is_active=False)
    response = client.post(
        "/api/v1/auth/login", json={"email": "inactive@example.com", "password": "Passw0rd1!"}
    )
    assert response.status_code == 401


def test_login_rate_limited_after_10_attempts(client):
    make_user(email="ratelimit@example.com", password="Passw0rd1!", role="customer")
    for _ in range(10):
        response = client.post(
            "/api/v1/auth/login", json={"email": "ratelimit@example.com", "password": "wrong"}
        )
        assert response.status_code == 401

    eleventh = client.post(
        "/api/v1/auth/login", json={"email": "ratelimit@example.com", "password": "wrong"}
    )
    assert eleventh.status_code == 429
    assert eleventh.json()["error"]["code"] == "RATE_LIMITED"


def test_refresh_rotation_and_reuse_rejected(client):
    make_user(email="refresh@example.com", password="Passw0rd1!", role="customer")
    tokens = login(client, "refresh@example.com", "Passw0rd1!")
    old_refresh = tokens["refreshToken"]

    first = client.post("/api/v1/auth/refresh", json={"refreshToken": old_refresh})
    assert first.status_code == 200, first.text
    new_refresh = first.json()["refreshToken"]
    assert new_refresh != old_refresh

    reuse = client.post("/api/v1/auth/refresh", json={"refreshToken": old_refresh})
    assert reuse.status_code == 401

    second = client.post("/api/v1/auth/refresh", json={"refreshToken": new_refresh})
    assert second.status_code == 200, second.text


def test_logout_revokes_refresh_token(client):
    make_user(email="logout@example.com", password="Passw0rd1!", role="customer")
    tokens = login(client, "logout@example.com", "Passw0rd1!")

    logout_response = client.post(
        "/api/v1/auth/logout",
        json={"refreshToken": tokens["refreshToken"]},
        headers=auth_header(tokens["accessToken"]),
    )
    assert logout_response.status_code == 204

    refresh_after_logout = client.post(
        "/api/v1/auth/refresh", json={"refreshToken": tokens["refreshToken"]}
    )
    assert refresh_after_logout.status_code == 401


def test_logout_requires_authentication(client):
    response = client.post("/api/v1/auth/logout", json={"refreshToken": "whatever"})
    assert response.status_code == 401


def test_me_returns_current_user(client):
    make_user(email="me@example.com", password="Passw0rd1!", role="customer")
    tokens = login(client, "me@example.com", "Passw0rd1!")
    response = client.get("/api/v1/auth/me", headers=auth_header(tokens["accessToken"]))
    assert response.status_code == 200, response.text
    assert response.json()["email"] == "me@example.com"
