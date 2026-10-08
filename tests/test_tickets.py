"""Ticket lifecycle: creation/numbering, status transitions, assignment, comments, history."""
from __future__ import annotations

from tests.conftest import auth_header, login, make_user


def _setup_roles(client):
    customer = make_user(role="customer")
    agent = make_user(role="agent")
    admin = make_user(role="admin")
    tokens = {
        "customer": login(client, customer["email"], customer["password"])["accessToken"],
        "agent": login(client, agent["email"], agent["password"])["accessToken"],
        "admin": login(client, admin["email"], admin["password"])["accessToken"],
    }
    return tokens, {"customer": customer, "agent": agent, "admin": admin}


def test_create_ticket_sequential_numbering(client):
    tokens, _ = _setup_roles(client)
    first = client.post(
        "/api/v1/tickets",
        json={"title": "First", "description": "d", "priority": "low", "category": "other"},
        headers=auth_header(tokens["customer"]),
    )
    second = client.post(
        "/api/v1/tickets",
        json={"title": "Second", "description": "d", "priority": "low", "category": "other"},
        headers=auth_header(tokens["customer"]),
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    n1 = first.json()["number"]
    n2 = second.json()["number"]
    assert n1.startswith("HD-")
    assert n2.startswith("HD-")
    assert int(n2.split("-")[1]) == int(n1.split("-")[1]) + 1
    assert first.json()["status"] == "open"
    assert first.json()["assigneeId"] is None
    assert first.json()["requesterId"]


def test_not_found_ticket_returns_404(client):
    tokens, _ = _setup_roles(client)
    response = client.get(
        "/api/v1/tickets/00000000-0000-0000-0000-000000000000", headers=auth_header(tokens["admin"])
    )
    assert response.status_code == 404


def test_valid_transition_chain_open_to_closed(client):
    tokens, _ = _setup_roles(client)
    created = client.post(
        "/api/v1/tickets",
        json={"title": "Chain", "description": "d", "priority": "medium", "category": "other"},
        headers=auth_header(tokens["customer"]),
    )
    ticket_id = created.json()["id"]

    to_in_progress = client.patch(
        f"/api/v1/tickets/{ticket_id}", json={"status": "in_progress"}, headers=auth_header(tokens["agent"])
    )
    assert to_in_progress.status_code == 200, to_in_progress.text
    assert to_in_progress.json()["status"] == "in_progress"

    to_resolved = client.patch(
        f"/api/v1/tickets/{ticket_id}", json={"status": "resolved"}, headers=auth_header(tokens["agent"])
    )
    assert to_resolved.status_code == 200, to_resolved.text
    assert to_resolved.json()["status"] == "resolved"
    assert to_resolved.json()["resolvedAt"] is not None

    to_closed = client.patch(
        f"/api/v1/tickets/{ticket_id}", json={"status": "closed"}, headers=auth_header(tokens["agent"])
    )
    assert to_closed.status_code == 200, to_closed.text
    assert to_closed.json()["status"] == "closed"


def test_invalid_transition_returns_409(client):
    tokens, _ = _setup_roles(client)
    created = client.post(
        "/api/v1/tickets",
        json={"title": "Invalid", "description": "d", "priority": "medium", "category": "other"},
        headers=auth_header(tokens["customer"]),
    )
    ticket_id = created.json()["id"]

    # open -> resolved directly is not a valid transition.
    response = client.patch(
        f"/api/v1/tickets/{ticket_id}", json={"status": "resolved"}, headers=auth_header(tokens["agent"])
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


def test_closed_to_in_progress_by_non_admin_rejected(client):
    tokens, _ = _setup_roles(client)
    created = client.post(
        "/api/v1/tickets",
        json={"title": "Closeme", "description": "d", "priority": "medium", "category": "other"},
        headers=auth_header(tokens["customer"]),
    )
    ticket_id = created.json()["id"]
    client.patch(f"/api/v1/tickets/{ticket_id}", json={"status": "in_progress"}, headers=auth_header(tokens["agent"]))
    client.patch(f"/api/v1/tickets/{ticket_id}", json={"status": "resolved"}, headers=auth_header(tokens["agent"]))
    client.patch(f"/api/v1/tickets/{ticket_id}", json={"status": "closed"}, headers=auth_header(tokens["agent"]))

    response = client.patch(
        f"/api/v1/tickets/{ticket_id}", json={"status": "in_progress"}, headers=auth_header(tokens["agent"])
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


def test_admin_can_reopen_closed_ticket(client):
    tokens, _ = _setup_roles(client)
    created = client.post(
        "/api/v1/tickets",
        json={"title": "Reopen me", "description": "d", "priority": "medium", "category": "other"},
        headers=auth_header(tokens["customer"]),
    )
    ticket_id = created.json()["id"]
    client.patch(f"/api/v1/tickets/{ticket_id}", json={"status": "in_progress"}, headers=auth_header(tokens["agent"]))
    client.patch(f"/api/v1/tickets/{ticket_id}", json={"status": "resolved"}, headers=auth_header(tokens["agent"]))
    client.patch(f"/api/v1/tickets/{ticket_id}", json={"status": "closed"}, headers=auth_header(tokens["agent"]))

    reopened = client.patch(
        f"/api/v1/tickets/{ticket_id}", json={"status": "open"}, headers=auth_header(tokens["admin"])
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "open"


def test_customer_can_edit_open_ticket_title_and_description(client):
    tokens, _ = _setup_roles(client)
    created = client.post(
        "/api/v1/tickets",
        json={"title": "Editable", "description": "d", "priority": "medium", "category": "other"},
        headers=auth_header(tokens["customer"]),
    )
    ticket_id = created.json()["id"]
    response = client.patch(
        f"/api/v1/tickets/{ticket_id}",
        json={"title": "Edited title", "description": "edited"},
        headers=auth_header(tokens["customer"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "Edited title"


def test_customer_cannot_set_status_or_assignee(client):
    tokens, _ = _setup_roles(client)
    created = client.post(
        "/api/v1/tickets",
        json={"title": "Locked fields", "description": "d", "priority": "medium", "category": "other"},
        headers=auth_header(tokens["customer"]),
    )
    ticket_id = created.json()["id"]
    response = client.patch(
        f"/api/v1/tickets/{ticket_id}", json={"status": "in_progress"}, headers=auth_header(tokens["customer"])
    )
    assert response.status_code == 422


def test_customer_cannot_edit_resolved_ticket(client):
    tokens, _ = _setup_roles(client)
    created = client.post(
        "/api/v1/tickets",
        json={"title": "Will be resolved", "description": "d", "priority": "medium", "category": "other"},
        headers=auth_header(tokens["customer"]),
    )
    ticket_id = created.json()["id"]
    client.patch(f"/api/v1/tickets/{ticket_id}", json={"status": "in_progress"}, headers=auth_header(tokens["agent"]))
    client.patch(f"/api/v1/tickets/{ticket_id}", json={"status": "resolved"}, headers=auth_header(tokens["agent"]))

    response = client.patch(
        f"/api/v1/tickets/{ticket_id}", json={"title": "nope"}, headers=auth_header(tokens["customer"])
    )
    assert response.status_code == 422


def test_assignee_must_be_active_agent_or_admin(client):
    tokens, users = _setup_roles(client)
    created = client.post(
        "/api/v1/tickets",
        json={"title": "Assign me", "description": "d", "priority": "medium", "category": "other"},
        headers=auth_header(tokens["customer"]),
    )
    ticket_id = created.json()["id"]

    # Assigning to a customer is invalid.
    bad = client.patch(
        f"/api/v1/tickets/{ticket_id}",
        json={"assigneeId": users["customer"]["id"]},
        headers=auth_header(tokens["agent"]),
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "INVALID_ASSIGNEE"

    # Assigning to a non-existent user is invalid.
    missing = client.patch(
        f"/api/v1/tickets/{ticket_id}",
        json={"assigneeId": "00000000-0000-0000-0000-000000000000"},
        headers=auth_header(tokens["agent"]),
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "INVALID_ASSIGNEE"

    # Assigning to an inactive agent is invalid.
    inactive_agent = make_user(role="agent", is_active=False)
    inactive = client.patch(
        f"/api/v1/tickets/{ticket_id}",
        json={"assigneeId": inactive_agent["id"]},
        headers=auth_header(tokens["agent"]),
    )
    assert inactive.status_code == 422
    assert inactive.json()["error"]["code"] == "INVALID_ASSIGNEE"

    # Assigning to an active agent succeeds.
    good = client.patch(
        f"/api/v1/tickets/{ticket_id}",
        json={"assigneeId": users["agent"]["id"]},
        headers=auth_header(tokens["agent"]),
    )
    assert good.status_code == 200, good.text
    assert good.json()["assigneeId"] == users["agent"]["id"]


def test_internal_comment_forbidden_for_customer(client):
    tokens, _ = _setup_roles(client)
    created = client.post(
        "/api/v1/tickets",
        json={"title": "Comments", "description": "d", "priority": "medium", "category": "other"},
        headers=auth_header(tokens["customer"]),
    )
    ticket_id = created.json()["id"]

    response = client.post(
        f"/api/v1/tickets/{ticket_id}/comments",
        json={"body": "secret", "internal": True},
        headers=auth_header(tokens["customer"]),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_customer_does_not_see_internal_comments(client):
    tokens, _ = _setup_roles(client)
    created = client.post(
        "/api/v1/tickets",
        json={"title": "Comments2", "description": "d", "priority": "medium", "category": "other"},
        headers=auth_header(tokens["customer"]),
    )
    ticket_id = created.json()["id"]

    client.post(
        f"/api/v1/tickets/{ticket_id}/comments",
        json={"body": "public note", "internal": False},
        headers=auth_header(tokens["agent"]),
    )
    client.post(
        f"/api/v1/tickets/{ticket_id}/comments",
        json={"body": "internal note", "internal": True},
        headers=auth_header(tokens["agent"]),
    )

    as_customer = client.get(f"/api/v1/tickets/{ticket_id}/comments", headers=auth_header(tokens["customer"]))
    assert as_customer.status_code == 200
    bodies = [c["body"] for c in as_customer.json()]
    assert "public note" in bodies
    assert "internal note" not in bodies

    as_agent = client.get(f"/api/v1/tickets/{ticket_id}/comments", headers=auth_header(tokens["agent"]))
    agent_bodies = [c["body"] for c in as_agent.json()]
    assert "internal note" in agent_bodies


def test_ticket_history_records_create_and_update(client):
    tokens, _ = _setup_roles(client)
    created = client.post(
        "/api/v1/tickets",
        json={"title": "History", "description": "d", "priority": "medium", "category": "other"},
        headers=auth_header(tokens["customer"]),
    )
    ticket_id = created.json()["id"]
    client.patch(f"/api/v1/tickets/{ticket_id}", json={"status": "in_progress"}, headers=auth_header(tokens["agent"]))

    response = client.get(f"/api/v1/tickets/{ticket_id}/history", headers=auth_header(tokens["admin"]))
    assert response.status_code == 200, response.text
    entries = response.json()
    actions = [e["action"] for e in entries]
    assert "created" in actions
    assert "updated" in actions
    assert entries[0]["actor"]["id"] is not None
