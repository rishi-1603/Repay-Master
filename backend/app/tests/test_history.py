"""Tests for /history: saved-scenario CRUD, scoped to the authenticated user."""
from app.tests.conftest import auth_headers, register_and_login


def test_list_history_empty_for_new_user(client):
    token = register_and_login(client, username="alice")
    resp = client.get("/history", headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_and_list_history_entry(client):
    token = register_and_login(client, username="alice")
    payload = {"label": "First home loan", "params": {"loan_amount": 500000, "interest_rate": 8.5}}
    create_resp = client.post("/history", json=payload, headers=auth_headers(token))
    assert create_resp.status_code == 201
    body = create_resp.json()
    assert body["label"] == "First home loan"
    assert body["params"] == payload["params"]
    assert isinstance(body["id"], int)

    list_resp = client.get("/history", headers=auth_headers(token))
    assert list_resp.status_code == 200
    entries = list_resp.json()
    assert len(entries) == 1
    assert entries[0]["id"] == body["id"]


def test_delete_own_history_entry(client):
    token = register_and_login(client, username="alice")
    create_resp = client.post(
        "/history", json={"label": "Car loan", "params": {"loan_amount": 20000}}, headers=auth_headers(token)
    )
    scenario_id = create_resp.json()["id"]

    delete_resp = client.delete(f"/history/{scenario_id}", headers=auth_headers(token))
    assert delete_resp.status_code == 204

    list_resp = client.get("/history", headers=auth_headers(token))
    assert list_resp.json() == []


def test_delete_nonexistent_entry_returns_404(client):
    token = register_and_login(client, username="alice")
    resp = client.delete("/history/999999", headers=auth_headers(token))
    assert resp.status_code == 404


def test_user_cannot_see_another_users_history(client):
    alice_token = register_and_login(client, username="alice")
    bob_token = register_and_login(client, username="bob")

    client.post("/history", json={"label": "Alice's loan", "params": {}}, headers=auth_headers(alice_token))

    bob_list = client.get("/history", headers=auth_headers(bob_token))
    assert bob_list.json() == []


def test_user_cannot_delete_another_users_history_entry(client):
    """Ownership must be enforced even when the id is guessed correctly --
    Bob should not be able to delete Alice's scenario just by knowing its id."""
    alice_token = register_and_login(client, username="alice")
    bob_token = register_and_login(client, username="bob")

    create_resp = client.post(
        "/history", json={"label": "Alice's loan", "params": {}}, headers=auth_headers(alice_token)
    )
    scenario_id = create_resp.json()["id"]

    delete_resp = client.delete(f"/history/{scenario_id}", headers=auth_headers(bob_token))
    assert delete_resp.status_code == 404

    alice_list = client.get("/history", headers=auth_headers(alice_token))
    assert len(alice_list.json()) == 1
