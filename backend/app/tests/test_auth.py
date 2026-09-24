"""Tests for /auth/register and /auth/login."""
from app.tests.conftest import auth_headers, register_and_login


def test_register_success(client):
    resp = client.post("/auth/register", json={"username": "bob", "password": "supersecret1"})
    assert resp.status_code == 201
    assert "successful" in resp.json()["message"].lower()


def test_register_duplicate_username_rejected(client):
    client.post("/auth/register", json={"username": "bob", "password": "supersecret1"})
    resp = client.post("/auth/register", json={"username": "bob", "password": "anotherpassword"})
    assert resp.status_code == 400
    assert "taken" in resp.json()["detail"].lower()


def test_register_short_password_rejected_by_schema(client):
    resp = client.post("/auth/register", json={"username": "bob", "password": "short"})
    assert resp.status_code == 422


def test_login_success_returns_bearer_token(client):
    client.post("/auth/register", json={"username": "bob", "password": "supersecret1"})
    resp = client.post("/auth/login", json={"username": "bob", "password": "supersecret1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) > 20


def test_login_wrong_password_rejected(client):
    client.post("/auth/register", json={"username": "bob", "password": "supersecret1"})
    resp = client.post("/auth/login", json={"username": "bob", "password": "wrongpassword"})
    assert resp.status_code == 401


def test_login_unknown_user_rejected(client):
    resp = client.post("/auth/login", json={"username": "ghost", "password": "whatever1"})
    assert resp.status_code == 401


def test_history_rejects_missing_token(client):
    resp = client.get("/history")
    assert resp.status_code == 401


def test_history_rejects_garbage_token(client):
    resp = client.get("/history", headers=auth_headers("not-a-real-jwt"))
    assert resp.status_code == 401


def test_registered_user_can_log_into_streamlit_auth_module_too(client):
    """The API and the Streamlit app share the same sqlite user table --
    prove it by calling utils.auth.authenticate directly, the same way
    app.py does, after registering purely through the HTTP API."""
    import utils.auth as auth_module

    client.post("/auth/register", json={"username": "carol", "password": "supersecret1"})
    ok, _ = auth_module.authenticate("carol", "supersecret1")
    assert ok is True


def test_full_register_login_flow_helper_works(client):
    token = register_and_login(client, username="dave")
    assert len(token) > 20
