"""Shared pytest fixtures for the RepayMaster API tests."""
import os
import sys
from pathlib import Path

# Must be set before anything under app/ is imported: app/core/config.py
# requires SECRET_KEY with no default (Day 3 fix -- see that file for why).
os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-production")

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import utils.auth as auth_module  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def isolated_auth_db(tmp_path, monkeypatch):
    """utils/auth.py always talks to a real sqlite file at a fixed repo path
    (shared with the Streamlit app). Tests must never read or write that
    real file -- monkeypatch the module-level DB_PATH to a fresh temp file
    per test, so test users/scenarios never leak into the app's real data
    and tests never see leftover state from a previous test run."""
    monkeypatch.setattr(auth_module, "DB_PATH", str(tmp_path / "test_app.db"))
    yield


def register_and_login(client: TestClient, username: str = "alice", password: str = "supersecret1") -> str:
    """Helper: register + login a fresh user, return their bearer token."""
    client.post("/auth/register", json={"username": username, "password": password})
    resp = client.post("/auth/login", json={"username": username, "password": password})
    return resp.json()["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
