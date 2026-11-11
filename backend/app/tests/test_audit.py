"""Audit trail: every privileged change leaves a record, written in the same transaction."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import cli
from app.core.security import create_access_token
from app.db.base import Base, get_db, get_engine, get_session_factory
from app.db.models import AuditEvent, RoleGrant, WebhookEvent
from app.main import app


@pytest.fixture()
def db_factory(tmp_path, monkeypatch):
    engine = get_engine(f"sqlite:///{tmp_path / 'audit.db'}")
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


@pytest.fixture()
def client(db_factory):
    return TestClient(app)


def auth(user):
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def audit_rows(db_factory):
    with db_factory() as s:
        return [(e.actor, e.action, e.target, e.detail) for e in s.query(AuditEvent).order_by(AuditEvent.id)]


def test_granting_and_revoking_a_role_is_audited_with_the_actor(client, db_factory):
    client.post("/admin/roles", json={"username": "newops", "role": "ops"}, headers=auth("root"))
    client.delete("/admin/roles/newops/ops", headers=auth("root"))
    assert audit_rows(db_factory) == [("root", "role.grant", "newops", "ops"),
                                      ("root", "role.revoke", "newops", "ops")]


def test_no_op_changes_write_no_audit_row(client, db_factory):
    client.post("/admin/roles", json={"username": "olivia", "role": "ops"}, headers=auth("root"))  # already held
    client.delete("/admin/roles/nobody/ops", headers=auth("root"))                              # not held
    assert audit_rows(db_factory) == []


def test_requeueing_a_dead_webhook_is_audited(client, db_factory):
    now = datetime.now(timezone.utc)
    with db_factory() as s:
        s.add(WebhookEvent(event_id="evt-d", event_type="payment.succeeded", payload="{}", status="DEAD",
                           attempts=5, next_attempt_at=now - timedelta(days=1), received_at=now))
        s.commit()
    assert client.post("/ops/webhooks/evt-d/requeue", headers=auth("root")).status_code == 200
    assert audit_rows(db_factory) == [("root", "webhook.requeue", "evt-d", None)]


def test_refused_requeue_writes_no_audit_row(client, db_factory):
    assert client.post("/ops/webhooks/evt-missing/requeue", headers=auth("root")).status_code == 404
    assert audit_rows(db_factory) == []


def test_audit_log_is_admin_only_newest_first_and_validates_limit(client, db_factory):
    client.post("/admin/roles", json={"username": "a1", "role": "ops"}, headers=auth("root"))
    client.post("/admin/roles", json={"username": "a2", "role": "ops"}, headers=auth("root"))
    assert client.get("/admin/audit", headers=auth("olivia")).status_code == 403
    assert client.get("/admin/audit", headers=auth("alice")).status_code == 403
    rows = client.get("/admin/audit", headers=auth("root")).json()
    assert [r["target"] for r in rows] == ["a2", "a1"]
    assert rows[0]["actor"] == "root" and rows[0]["created_at"]
    assert client.get("/admin/audit?limit=0", headers=auth("root")).status_code == 422


def test_cli_changes_are_audited_as_cli(db_factory, monkeypatch, capsys):
    monkeypatch.setattr(cli, "session_factory", lambda: db_factory)
    cli.main(["grant-role", "carol", "ops"])
    cli.main(["revoke-role", "carol", "ops"])
    assert audit_rows(db_factory) == [("cli", "role.grant", "carol", "ops"),
                                      ("cli", "role.revoke", "carol", "ops")]
