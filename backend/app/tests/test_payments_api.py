"""Integration tests: real API, real transactions, temporary SQLite database."""
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token
from app.db.base import Base, get_db, get_engine
from app.db.models import JournalEntry, LoanAccount, Payment, WebhookEvent
from app.domain.payments import sign_payload
from app.main import app

SECRET = "webhook-test-secret-0123456789"


@pytest.fixture()
def db_session_factory(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'ledger.db'}"
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    from sqlalchemy.orm import sessionmaker
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _get_db():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    monkeypatch.setitem(app.dependency_overrides, get_db, _get_db)
    monkeypatch.setattr(settings, "PAYMENT_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(settings, "ADMIN_USERNAMES", "ops")
    yield factory
    app.dependency_overrides.pop(get_db, None)
    get_engine.cache_clear()
    engine.dispose()


def auth(user: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def webhook(client: TestClient, event_id: str, event_type: str, data: dict, secret: str = SECRET):
    import json
    body = json.dumps({"id": event_id, "type": event_type, "data": data}, separators=(",", ":")).encode()
    header = sign_payload(secret, body, int(time.time()))
    return client.post("/webhooks/payments", content=body,
                       headers={"Content-Type": "application/json", "X-Webhook-Signature": header})


@pytest.fixture()
def loan(db_session_factory):
    client = TestClient(app)
    resp = client.post("/loans", json={"loan_id": "LN-1001", "principal_outstanding": 100,
                                       "interest_due": 5, "fees_due": 1}, headers=auth("alice"))
    assert resp.status_code == 201, resp.text
    return client


def new_payment(client, amount, key="key-0000001", user="alice"):
    return client.post("/loans/LN-1001/payments", json={"amount": amount, "idempotency_key": key},
                       headers=auth(user))


def trial(client):
    return client.get("/ledger/trial-balance", headers=auth("ops")).json()


def test_loan_creation_and_ownership(loan):
    body = loan.get("/loans/LN-1001", headers=auth("alice")).json()
    assert body["total_owed"] == "106.00" and body["principal_outstanding"] == "100.00"
    assert loan.get("/loans/LN-1001", headers=auth("mallory")).status_code == 404
    assert loan.post("/loans", json={"loan_id": "LN-1001", "principal_outstanding": 1},
                     headers=auth("alice")).status_code == 409


def test_payment_intent_is_idempotent_and_conflicts_on_changed_amount(loan):
    first = new_payment(loan, 50)
    assert first.status_code == 201
    replay = new_payment(loan, 50)
    assert replay.json()["reference"] == first.json()["reference"]
    assert replay.json()["state"] == "PENDING"
    conflict = new_payment(loan, 60)
    assert conflict.status_code == 409


def test_overpayment_at_intent_time_is_422(loan):
    assert new_payment(loan, 106.01, key="key-over-0001").status_code == 422


def test_webhook_refuses_unsigned_bad_and_stale_requests(loan, monkeypatch):
    ref = new_payment(loan, 50).json()["reference"]
    data = {"reference": ref, "provider_reference": "P1"}
    assert webhook(loan, "evt-1", "payment.succeeded", data, secret="wrong").status_code == 401
    assert loan.post("/webhooks/payments", content=b"{}").status_code == 401
    monkeypatch.setattr(settings, "PAYMENT_WEBHOOK_SECRET", None)
    assert webhook(loan, "evt-1", "payment.succeeded", data).status_code == 503


def test_successful_payment_applies_waterfall_and_posts_balanced_entry(loan):
    ref = new_payment(loan, 60).json()["reference"]
    resp = webhook(loan, "evt-ok", "payment.succeeded", {"reference": ref, "provider_reference": "P1"})
    assert resp.json()["result"] == "applied"
    body = loan.get("/loans/LN-1001", headers=auth("alice")).json()
    # 60 paid: fees 1.00 first, then interest 5.00, then principal 54.00 -> outstanding 46.00
    assert body["fees_due"] == "0.00"
    assert body["interest_due"] == "0.00"
    assert body["principal_outstanding"] == "46.00"
    assert body["payments"][0]["state"] == "SUCCESSFUL"
    t = trial(loan)
    assert t["balanced"] is True and t["entry_count"] == 1


def test_duplicate_webhooks_apply_money_exactly_once(loan):
    ref = new_payment(loan, 60).json()["reference"]
    data = {"reference": ref, "provider_reference": "P1"}
    results = [webhook(loan, "evt-dup", "payment.succeeded", data).json()["result"] for _ in range(3)]
    assert results == ["applied", "duplicate", "duplicate"]
    body = loan.get("/loans/LN-1001", headers=auth("alice")).json()
    assert body["principal_outstanding"] == "46.00"
    assert trial(loan)["entry_count"] == 1


def test_different_event_ids_for_same_payment_do_not_double_post(loan):
    ref = new_payment(loan, 60).json()["reference"]
    data = {"reference": ref, "provider_reference": "P1"}
    assert webhook(loan, "evt-a", "payment.succeeded", data).json()["result"] == "applied"
    assert webhook(loan, "evt-b", "payment.succeeded", data).json()["result"] == "already_applied"
    assert trial(loan)["entry_count"] == 1


def test_failed_payment_can_be_retried_then_succeed(loan):
    ref = new_payment(loan, 60).json()["reference"]
    assert webhook(loan, "evt-f", "payment.failed", {"reference": ref}).json()["result"] == "applied"
    assert loan.post(f"/payments/{ref}/retry", headers=auth("alice")).json()["state"] == "PENDING"
    assert webhook(loan, "evt-s", "payment.succeeded",
                   {"reference": ref, "provider_reference": "P2"}).json()["result"] == "applied"
    assert trial(loan)["balanced"] is True


def test_reversal_restores_balances_and_nets_ledger_to_zero(loan):
    ref = new_payment(loan, 60).json()["reference"]
    webhook(loan, "evt-s", "payment.succeeded", {"reference": ref, "provider_reference": "P1"})
    assert webhook(loan, "evt-r", "payment.reversed", {"reference": ref}).json()["result"] == "applied"
    body = loan.get("/loans/LN-1001", headers=auth("alice")).json()
    assert body["principal_outstanding"] == "100.00"
    assert body["total_owed"] == "106.00"
    t = trial(loan)
    assert t["balanced"] is True
    assert t["accounts"]["payment_clearing"] == "0.00"
    assert t["accounts"]["loan_receivable"] == "0.00"
    assert t["entry_count"] == 2


def test_success_for_a_failed_payment_is_parked_in_suspense_not_applied(loan):
    ref = new_payment(loan, 60).json()["reference"]
    webhook(loan, "evt-f", "payment.failed", {"reference": ref})
    result = webhook(loan, "evt-late", "payment.succeeded",
                     {"reference": ref, "provider_reference": "P9"}).json()["result"]
    assert result == "needs_review"
    body = loan.get("/loans/LN-1001", headers=auth("alice")).json()
    assert body["principal_outstanding"] == "100.00"
    t = trial(loan)
    assert t["balanced"] is True
    assert t["accounts"]["suspense"] == "60.00"


def test_unknown_payment_and_unknown_event_type_are_recorded_not_fatal(loan):
    assert webhook(loan, "evt-x", "payment.succeeded",
                   {"reference": "PAY-NOPE", "provider_reference": "P"}).json()["result"] == "unknown_payment"
    assert webhook(loan, "evt-y", "payment.disputed", {"reference": "PAY-NOPE"}).json()["result"] == "ignored"


def test_reconciliation_and_trial_balance_are_operations_only(loan):
    ref = new_payment(loan, 60).json()["reference"]
    webhook(loan, "evt-s", "payment.succeeded", {"reference": ref, "provider_reference": "P1"})
    assert loan.post("/reconciliation/run", json={"settlement": []}, headers=auth("alice")).status_code == 403
    assert loan.get("/ledger/trial-balance", headers=auth("alice")).status_code == 403
    recon = loan.post("/reconciliation/run", json={"settlement": [
        {"reference": ref, "amount": 60, "status": "settled"},
        {"reference": ref, "amount": 60, "status": "settled"},
    ]}, headers=auth("ops")).json()
    types = {e["type"] for e in recon["exceptions"]}
    assert types == {"DUPLICATE_SETTLEMENT"}


def test_reconciliation_flags_settled_but_unposted_and_missing_settlement(loan):
    ref = new_payment(loan, 60).json()["reference"]
    recon = loan.post("/reconciliation/run", json={"settlement": [
        {"reference": ref, "amount": 60, "status": "settled"}]}, headers=auth("ops")).json()
    assert {e["type"] for e in recon["exceptions"]} == {"NOT_POSTED_INTERNALLY"}
    webhook(loan, "evt-s", "payment.succeeded", {"reference": ref, "provider_reference": "P1"})
    recon2 = loan.post("/reconciliation/run", json={"settlement": []}, headers=auth("ops")).json()
    assert {e["type"] for e in recon2["exceptions"]} == {"MISSING_SETTLEMENT"}


def test_webhook_events_are_persisted_for_audit(loan, db_session_factory):
    ref = new_payment(loan, 60).json()["reference"]
    webhook(loan, "evt-audit", "payment.succeeded", {"reference": ref, "provider_reference": "P1"})
    with db_session_factory() as s:
        ev = s.scalar(select(WebhookEvent).where(WebhookEvent.event_id == "evt-audit"))
        assert ev.result == "applied" and "PAY-" in ev.payload
        assert s.scalar(select(Payment).where(Payment.reference == ref)).state == "SUCCESSFUL"
        assert s.scalar(select(LoanAccount).where(LoanAccount.id == "LN-1001")).principal_outstanding == 4600
        assert s.scalar(select(JournalEntry).where(JournalEntry.idempotency_key.like("payment:%"))) is not None
