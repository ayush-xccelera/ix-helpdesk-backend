"""Role-based access control tests: user listing scoping, admin-only endpoints,
self-demotion/deactivation protection, and ticket visibility scoping."""
from __future__ import annotations

from tests.conftest import auth_header, login, make_user


def _token_for(client, **user_kwargs) -> tuple[str, dict]:
    user = make_user(**user_kwargs)
    tokens = login(client, user["email"], user["password"])
    return tokens["accessToken"], user


def test_customer_cannot_list_users(client):
    token, _ = _token_for(client, role="customer")
    response = client.get("/api/v1/users", headers=auth_header(token))
    assert response.status_code == 403


def test_agent_can_list_with_role_agent_filter(client):
    token, _ = _token_for(client, role="agent")
    make_user(role="agent")
    response = client.get("/api/v1/users?role=agent", headers=auth_header(token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert all(item["role"] == "agent" for item in body["items"])


def test_agent_cannot_list_all_users(client):
    token, _ = _token_for(client, role="agent")
    response = client.get("/api/v1/users", headers=auth_header(token))
    assert response.status_code == 403


def test_agent_cannot_list_other_roles(client):
    token, _ = _token_for(client, role="agent")
    response = client.get("/api/v1/users?role=customer", headers=auth_header(token))
    assert response.status_code == 403


def test_admin_can_list_all_users(client):
    token, _ = _token_for(client, role="admin")
    make_user(role="customer")
    make_user(role="agent")
    response = client.get("/api/v1/users", headers=auth_header(token))
    assert response.status_code == 200, response.text
    assert response.json()["total"] >= 3


def test_only_admin_can_create_user(client):
    customer_token, _ = _token_for(client, role="customer")
    agent_token, _ = _token_for(client, role="agent")
    admin_token, _ = _token_for(client, role="admin")

    payload = {"fullName": "Created", "email": "created1@example.com", "password": "Passw0rd1!", "role": "agent"}
    assert client.post("/api/v1/users", json=payload, headers=auth_header(customer_token)).status_code == 403

    payload["email"] = "created2@example.com"
    assert client.post("/api/v1/users", json=payload, headers=auth_header(agent_token)).status_code == 403

    payload["email"] = "created3@example.com"
    response = client.post("/api/v1/users", json=payload, headers=auth_header(admin_token))
    assert response.status_code == 201, response.text


def test_only_admin_can_patch_user(client):
    admin_token, _ = _token_for(client, role="admin")
    agent_token, agent_user = _token_for(client, role="agent")
    customer_token, _ = _token_for(client, role="customer")

    denied = client.patch(
        f"/api/v1/users/{agent_user['id']}", json={"fullName": "x"}, headers=auth_header(customer_token)
    )
    assert denied.status_code == 403

    denied2 = client.patch(
        f"/api/v1/users/{agent_user['id']}", json={"fullName": "x"}, headers=auth_header(agent_token)
    )
    assert denied2.status_code == 403

    allowed = client.patch(
        f"/api/v1/users/{agent_user['id']}", json={"fullName": "Updated Name"}, headers=auth_header(admin_token)
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["fullName"] == "Updated Name"


def test_admin_cannot_demote_self(client):
    admin_token, admin_user = _token_for(client, role="admin")
    response = client.patch(
        f"/api/v1/users/{admin_user['id']}", json={"role": "agent"}, headers=auth_header(admin_token)
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SELF_MODIFICATION_FORBIDDEN"


def test_admin_cannot_deactivate_self(client):
    admin_token, admin_user = _token_for(client, role="admin")
    response = client.patch(
        f"/api/v1/users/{admin_user['id']}", json={"isActive": False}, headers=auth_header(admin_token)
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SELF_MODIFICATION_FORBIDDEN"


def test_admin_can_update_own_full_name(client):
    admin_token, admin_user = _token_for(client, role="admin")
    response = client.patch(
        f"/api/v1/users/{admin_user['id']}", json={"fullName": "Still Admin"}, headers=auth_header(admin_token)
    )
    assert response.status_code == 200, response.text


def test_audit_log_is_admin_only(client):
    customer_token, _ = _token_for(client, role="customer")
    agent_token, _ = _token_for(client, role="agent")
    admin_token, _ = _token_for(client, role="admin")

    assert client.get("/api/v1/audit", headers=auth_header(customer_token)).status_code == 403
    assert client.get("/api/v1/audit", headers=auth_header(agent_token)).status_code == 403
    assert client.get("/api/v1/audit", headers=auth_header(admin_token)).status_code == 200


def test_customer_cannot_see_others_tickets(client):
    owner_token, _owner = _token_for(client, role="customer")
    other_token, _ = _token_for(client, role="customer")

    created = client.post(
        "/api/v1/tickets",
        json={"title": "Private ticket", "description": "d", "priority": "low", "category": "other"},
        headers=auth_header(owner_token),
    )
    ticket_id = created.json()["id"]

    response = client.get(f"/api/v1/tickets/{ticket_id}", headers=auth_header(other_token))
    assert response.status_code == 403


def test_customer_ticket_list_scoped_to_own(client):
    owner_token, _owner = _token_for(client, role="customer")
    other_token, _ = _token_for(client, role="customer")

    client.post(
        "/api/v1/tickets",
        json={"title": "Mine", "description": "d", "priority": "low", "category": "other"},
        headers=auth_header(owner_token),
    )
    client.post(
        "/api/v1/tickets",
        json={"title": "Theirs", "description": "d", "priority": "low", "category": "other"},
        headers=auth_header(other_token),
    )

    response = client.get("/api/v1/tickets", headers=auth_header(owner_token))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "Mine"


def test_dashboard_forbidden_for_customer(client):
    token, _ = _token_for(client, role="customer")
    response = client.get("/api/v1/dashboard/summary", headers=auth_header(token))
    assert response.status_code == 403


def test_dashboard_allowed_for_agent_and_admin(client):
    agent_token, _ = _token_for(client, role="agent")
    admin_token, _ = _token_for(client, role="admin")
    assert client.get("/api/v1/dashboard/summary", headers=auth_header(agent_token)).status_code == 200
    assert client.get("/api/v1/dashboard/summary", headers=auth_header(admin_token)).status_code == 200
