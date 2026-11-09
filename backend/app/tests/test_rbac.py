"""Role-based access: ops and admin grants, per-request checks, requeue, and the operator CLI."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import cli
from app.core.security import create_access_token
from app.db.base import Base, get_db, get_engine, get_session_factory
from app.db.models import RoleGrant, WebhookEvent
from app.main import app
from app.services import roles


@pytest.fixture()
def db_factory(tmp_path, monkeypatch):
    engine = get_engine(f"sqlite:///{tmp_path / 'rbac.db'}")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _get_db():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    monkeypatch.setitem(app.dependency_overrides, get_db, _get_db)
    monkeypatch.setitem(app.dependency_overrides, get_session_factory, lambda: factory)
    with factory() as s:
        s.add(RoleGrant(username="root", role="admin"))
        s.add(RoleGrant(username="olivia", role="ops"))
        s.commit()
    yield factory
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_session_factory, None)
    Base.metadata.drop_all(engine)
    get_engine.cache_clear()
    engine.dispose()


def auth(user: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


OPS_ENDPOINTS = [
    ("get", "/ops/webhooks", None),
    ("post", "/ops/webhooks/drain", None),
    ("post", "/reconciliation/run", {"settlement": []}),
    ("get", "/ledger/trial-balance", None),
    ("get", "/ledger/integrity", None),
]


def call(client, method, path, user, body=None):
    kwargs = {"headers": auth(user)} if user else {}
    if body is not None:
        kwargs["json"] = body
    return getattr(client, method)(path, **kwargs)


@pytest.fixture()
def client(db_factory):
    return TestClient(app)


def test_operations_endpoints_require_authentication(client):
    for method, path, body in OPS_ENDPOINTS:
        assert call(client, method, path, None, body).status_code == 401


def test_customers_without_a_grant_are_refused_every_operations_endpoint(client):
    for method, path, body in OPS_ENDPOINTS:
        assert call(client, method, path, "alice", body).status_code == 403, path
    assert call(client, "post", "/ops/webhooks/evt-x/requeue", "alice").status_code == 403
    assert call(client, "post", "/admin/roles", "alice", {"username": "alice", "role": "ops"}).status_code == 403


def test_ops_role_can_run_operations_but_cannot_administer_roles_or_requeue(client, db_factory):
    for method, path, body in OPS_ENDPOINTS:
        assert call(client, method, path, "olivia", body).status_code in (200, 201), path
    assert call(client, "post", "/ops/webhooks/evt-x/requeue", "olivia").status_code == 403
    grant = call(client, "post", "/admin/roles", "olivia", {"username": "mallory", "role": "ops"})
    assert grant.status_code == 403
    with db_factory() as s:
        assert roles.granted_roles(s, "mallory") == set()


def test_admin_implies_ops_without_a_separate_grant(client):
    for method, path, body in OPS_ENDPOINTS:
        assert call(client, method, path, "root", body).status_code in (200, 201), path


def test_admin_grants_and_revokes_ops_and_the_effect_is_immediate(client):
    token_user = "newops"
    assert call(client, "get", "/ledger/integrity", token_user).status_code == 403
    created = call(client, "post", "/admin/roles", "root", {"username": token_user, "role": "ops"})
    assert created.status_code == 201 and created.json()["created"] is True
    assert call(client, "get", "/ledger/integrity", token_user).status_code == 200
    again = call(client, "post", "/admin/roles", "root", {"username": token_user, "role": "ops"}).json()
    assert again["created"] is False                              # idempotent
    assert call(client, "get", f"/admin/roles/{token_user}", "root").json()["roles"] == ["ops"]
    assert call(client, "delete", f"/admin/roles/{token_user}/ops", "root").status_code == 200
    # same token, next request: the revoke is already in force (roles are not read from the token)
    assert call(client, "get", "/ledger/integrity", token_user).status_code == 403


def test_role_administration_rejects_unknown_roles_and_missing_grants(client):
    assert call(client, "post", "/admin/roles", "root", {"username": "x", "role": "superuser"}).status_code == 422
    assert call(client, "delete", "/admin/roles/olivia/admin", "root").status_code == 404
    assert call(client, "delete", "/admin/roles/olivia/superuser", "root").status_code == 422


def test_requeue_only_applies_to_dead_events_and_the_event_is_processed_again(client, db_factory):
    now = datetime.now(timezone.utc)
    with db_factory() as s:
        s.add(WebhookEvent(event_id="evt-dead", event_type="payment.succeeded",
                           payload=json.dumps({"id": "evt-dead", "type": "payment.succeeded", "data": {}}),
                           status="DEAD", attempts=5, next_attempt_at=now - timedelta(days=1), received_at=now))
        s.add(WebhookEvent(event_id="evt-live", event_type="payment.succeeded", payload="{}",
                           status="RECEIVED", attempts=0, next_attempt_at=now, received_at=now))
        s.commit()
    assert call(client, "post", "/ops/webhooks/evt-live/requeue", "root").status_code == 409
    assert call(client, "post", "/ops/webhooks/evt-missing/requeue", "root").status_code == 404
    resp = call(client, "post", "/ops/webhooks/evt-dead/requeue", "root")
    assert resp.status_code == 200 and resp.json() == {"event_id": "evt-dead", "status": "RECEIVED", "attempts": 0}
    drained = call(client, "post", "/ops/webhooks/drain", "olivia").json()
    assert drained["processed"] == 1
    listing = call(client, "get", "/ops/webhooks", "olivia").json()
    assert [e["status"] for e in listing if e["event_id"] == "evt-dead"] == ["PROCESSED"]


def test_cli_grants_and_revokes_roles_in_the_database(db_factory, monkeypatch, capsys):
    monkeypatch.setattr(cli, "session_factory", lambda: db_factory)
    assert cli.main(["grant-role", "carol", "ops"]) == 0
    assert "granted ops to carol" in capsys.readouterr().out
    assert cli.main(["grant-role", "carol", "ops"]) == 0
    assert "already has ops" in capsys.readouterr().out
    with db_factory() as s:
        assert roles.granted_roles(s, "carol") == {"ops"}
    assert cli.main(["revoke-role", "carol", "ops"]) == 0
    assert "revoked ops from carol" in capsys.readouterr().out
    with db_factory() as s:
        assert roles.granted_roles(s, "carol") == set()


def test_cli_rejects_roles_it_does_not_know(monkeypatch):
    with pytest.raises(SystemExit):
        cli.main(["grant-role", "carol", "superuser"])
