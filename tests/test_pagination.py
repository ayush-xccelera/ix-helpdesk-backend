"""Pagination behavior: page/pageSize, pageSize cap at 100 for tickets, case-insensitive q search."""
from __future__ import annotations

from tests.conftest import auth_header, login, make_user


def test_user_pagination_and_case_insensitive_search(client):
    admin = make_user(role="admin")
    admin_token = login(client, admin["email"], admin["password"])["accessToken"]

    for i in range(5):
        make_user(role="customer", full_name=f"Searchable Person {i}", email=f"searchable{i}@example.com")
    for i in range(5):
        make_user(role="customer", full_name=f"Other Person {i}", email=f"other{i}@example.com")

    response = client.get(
        "/api/v1/users?q=SEARCHABLE&page=1&pageSize=3", headers=auth_header(admin_token)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 5
    assert body["page"] == 1
    assert body["pageSize"] == 3
    assert len(body["items"]) == 3

    page2 = client.get("/api/v1/users?q=searchable&page=2&pageSize=3", headers=auth_header(admin_token))
    assert page2.status_code == 200
    assert len(page2.json()["items"]) == 2


def test_ticket_pagination_page_size_cap(client):
    customer = make_user(role="customer")
    token = login(client, customer["email"], customer["password"])["accessToken"]

    for i in range(5):
        client.post(
            "/api/v1/tickets",
            json={"title": f"Ticket {i}", "description": "d", "priority": "low", "category": "other"},
            headers=auth_header(token),
        )

    # pageSize is capped at 100 — a request exceeding it is a validation error.
    response = client.get("/api/v1/tickets?pageSize=1000", headers=auth_header(token))
    assert response.status_code == 422, response.text

    at_cap = client.get("/api/v1/tickets?pageSize=100", headers=auth_header(token))
    assert at_cap.status_code == 200, at_cap.text
    assert at_cap.json()["pageSize"] == 100
    assert at_cap.json()["total"] == 5


def test_ticket_pagination_basic(client):
    customer = make_user(role="customer")
    token = login(client, customer["email"], customer["password"])["accessToken"]

    for i in range(5):
        client.post(
            "/api/v1/tickets",
            json={"title": f"Page {i}", "description": "d", "priority": "low", "category": "other"},
            headers=auth_header(token),
        )

    page1 = client.get("/api/v1/tickets?page=1&pageSize=2", headers=auth_header(token))
    assert page1.status_code == 200
    body1 = page1.json()
    assert len(body1["items"]) == 2
    assert body1["total"] == 5

    page3 = client.get("/api/v1/tickets?page=3&pageSize=2", headers=auth_header(token))
    assert len(page3.json()["items"]) == 1


def test_ticket_q_search_case_insensitive_over_title_and_description(client):
    customer = make_user(role="customer")
    token = login(client, customer["email"], customer["password"])["accessToken"]

    client.post(
        "/api/v1/tickets",
        json={"title": "Printer issue", "description": "nothing special", "priority": "low", "category": "hardware"},
        headers=auth_header(token),
    )
    client.post(
        "/api/v1/tickets",
        json={
            "title": "VPN problem",
            "description": "cannot connect to PRINTER share",
            "priority": "low",
            "category": "network",
        },
        headers=auth_header(token),
    )
    client.post(
        "/api/v1/tickets",
        json={"title": "Unrelated", "description": "nothing here", "priority": "low", "category": "other"},
        headers=auth_header(token),
    )

    response = client.get("/api/v1/tickets?q=printer", headers=auth_header(token))
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 2
