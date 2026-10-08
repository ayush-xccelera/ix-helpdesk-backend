"""SLA computation and breach-detection tests."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app.models import Ticket
from tests.conftest import auth_header, login, make_user


def _create_ticket(client, token, priority="medium"):
    response = client.post(
        "/api/v1/tickets",
        json={"title": "SLA test", "description": "d", "priority": priority, "category": "other"},
        headers=auth_header(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _push_sla_due_into_past(ticket_id: str, hours_ago: float = 1.0) -> None:
    db = SessionLocal()
    try:
        ticket = db.get(Ticket, uuid.UUID(ticket_id))
        ticket.sla_due_at = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        db.commit()
    finally:
        db.close()


def test_sla_due_at_computed_by_priority(client):
    customer = make_user(role="customer")
    token = login(client, customer["email"], customer["password"])["accessToken"]

    expectations = {"urgent": 4, "high": 8, "medium": 24, "low": 72}
    for priority, hours in expectations.items():
        before = datetime.now(timezone.utc)
        ticket = _create_ticket(client, token, priority=priority)
        due_at = datetime.fromisoformat(ticket["slaDueAt"].replace("Z", "+00:00"))
        created_at = datetime.fromisoformat(ticket["createdAt"].replace("Z", "+00:00"))
        assert abs((due_at - created_at) - timedelta(hours=hours)) < timedelta(seconds=5)
        assert due_at > before


def test_sla_not_breached_for_fresh_open_ticket(client):
    customer = make_user(role="customer")
    token = login(client, customer["email"], customer["password"])["accessToken"]
    ticket = _create_ticket(client, token, priority="low")
    assert ticket["slaBreached"] is False


def test_sla_breached_for_overdue_open_ticket(client):
    customer = make_user(role="customer")
    token = login(client, customer["email"], customer["password"])["accessToken"]
    ticket = _create_ticket(client, token, priority="urgent")
    _push_sla_due_into_past(ticket["id"])

    response = client.get(f"/api/v1/tickets/{ticket['id']}", headers=auth_header(token))
    assert response.status_code == 200
    assert response.json()["slaBreached"] is True


def test_sla_breached_for_late_resolved_ticket(client):
    customer = make_user(role="customer")
    agent = make_user(role="agent")
    customer_token = login(client, customer["email"], customer["password"])["accessToken"]
    agent_token = login(client, agent["email"], agent["password"])["accessToken"]

    ticket = _create_ticket(client, customer_token, priority="urgent")
    _push_sla_due_into_past(ticket["id"])

    in_progress = client.patch(
        f"/api/v1/tickets/{ticket['id']}", json={"status": "in_progress"}, headers=auth_header(agent_token)
    )
    assert in_progress.status_code == 200, in_progress.text

    resolved = client.patch(
        f"/api/v1/tickets/{ticket['id']}", json={"status": "resolved"}, headers=auth_header(agent_token)
    )
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["resolvedAt"] is not None
    assert body["slaBreached"] is True


def test_sla_not_breached_for_timely_resolved_ticket(client):
    customer = make_user(role="customer")
    agent = make_user(role="agent")
    customer_token = login(client, customer["email"], customer["password"])["accessToken"]
    agent_token = login(client, agent["email"], agent["password"])["accessToken"]

    ticket = _create_ticket(client, customer_token, priority="low")

    client.patch(f"/api/v1/tickets/{ticket['id']}", json={"status": "in_progress"}, headers=auth_header(agent_token))
    resolved = client.patch(
        f"/api/v1/tickets/{ticket['id']}", json={"status": "resolved"}, headers=auth_header(agent_token)
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["slaBreached"] is False
