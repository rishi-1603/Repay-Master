"""Integration tests: real API, real transactions, worker-driven webhook processing.

Runs on SQLite by default. Set TEST_DATABASE_URL=postgresql+psycopg://... to run the
same tests against PostgreSQL (the CI job does this as well).
"""
import json
import os
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.security import create_access_token
from app.db.base import Base, get_db, get_engine, get_session_factory
from app.db.models import JournalEntry, LoanAccount, Payment, RoleGrant, WebhookEvent
from app.domain.payments import sign_payload
from app.main import app
from app.services import payments as payments_service

SECRET = "webhook-test-secret-0123456789"
PG_URL = os.environ.get("TEST_DATABASE_URL", "")


@pytest.fixture()
def db_factory(tmp_path, monkeypatch):
    url = PG_URL or f"sqlite:///{tmp_path / 'ledger.db'}"
    engine = get_engine(url)
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
    monkeypatch.setattr(settings, "PAYMENT_WEBHOOK_SECRET", SECRET)
    with factory() as s:
        s.add(RoleGrant(username="ops", role="ops"))   # operations role lives in the database now
        s.commit()
    yield factory
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_session_factory, None)
    Base.metadata.drop_all(engine)
    get_engine.cache_clear()
    engine.dispose()


def auth(user: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def send_webhook(client: TestClient, event_id: str, event_type: str, data: dict, secret: str = SECRET):
    body = json.dumps({"id": event_id, "type": event_type, "data": data}, separators=(",", ":")).encode()
    header = sign_payload(secret, body, int(time.time()))
    return client.post("/webhooks/payments", content=body,
                       headers={"Content-Type": "application/json", "X-Webhook-Signature": header})


def drain(client: TestClient) -> dict:
    resp = client.post("/ops/webhooks/drain", headers=auth("ops"))
    assert resp.status_code == 200, resp.text
    return resp.json()


def webhook(client: TestClient, event_id: str, event_type: str, data: dict) -> str:
    """Deliver and process one webhook; return the processing result."""
    assert send_webhook(client, event_id, event_type, data).status_code == 202
    summary = drain(client)
    assert summary["claimed"] >= 1 or summary["processed"] == 0
    row = client.get("/ops/webhooks", headers=auth("ops")).json()
    match = [r for r in row if r["event_id"] == event_id]
    return match[0]["result"] if match else "missing"


@pytest.fixture()
def client(db_factory):
    c = TestClient(app)
    resp = c.post("/loans", json={"loan_id": "LN-1001", "principal_outstanding": 100,
                                  "interest_due": 5, "fees_due": 1}, headers=auth("alice"))
    assert resp.status_code == 201, resp.text
    return c


def new_payment(client, amount, key="key-0000001", user="alice"):
    return client.post("/loans/LN-1001/payments", json={"amount": amount, "idempotency_key": key},
                       headers=auth(user))


def trial(client):
    return client.get("/ledger/trial-balance", headers=auth("ops")).json()


def test_loan_creation_and_ownership(client):
    body = client.get("/loans/LN-1001", headers=auth("alice")).json()
    assert body["total_owed"] == "106.00" and body["principal_outstanding"] == "100.00"
    assert body["principal_original"] == "100.00"
    assert client.get("/loans/LN-1001", headers=auth("mallory")).status_code == 404
    assert client.post("/loans", json={"loan_id": "LN-1001", "principal_outstanding": 1},
                       headers=auth("alice")).status_code == 409


def test_payment_intent_is_idempotent_and_conflicts_on_changed_amount(client):
    first = new_payment(client, 50)
    assert first.status_code == 201
    replay = new_payment(client, 50)
    assert replay.json()["reference"] == first.json()["reference"]
    assert new_payment(client, 60).status_code == 409


def test_overpayment_is_accepted_at_intent_time(client):
    resp = new_payment(client, 106.01, key="key-over-0001")
    assert resp.status_code == 201 and resp.json()["state"] == "PENDING"


def test_webhook_refuses_unsigned_bad_and_unconfigured_requests(client, monkeypatch):
    ref = new_payment(client, 50).json()["reference"]
    data = {"reference": ref, "provider_reference": "P1"}
    assert send_webhook(client, "evt-1", "payment.succeeded", data, secret="wrong").status_code == 401
    assert client.post("/webhooks/payments", content=b"{}").status_code == 401
    monkeypatch.setattr(settings, "PAYMENT_WEBHOOK_SECRET", None)
    assert send_webhook(client, "evt-1", "payment.succeeded", data).status_code == 503


def test_webhook_is_acknowledged_before_processing(client):
    ref = new_payment(client, 60).json()["reference"]
    resp = send_webhook(client, "evt-q", "payment.succeeded", {"reference": ref, "provider_reference": "P1"})
    assert resp.status_code == 202 and resp.json()["status"] == "queued"
    # Not yet applied: the worker has not run.
    assert client.get("/loans/LN-1001", headers=auth("alice")).json()["principal_outstanding"] == "100.00"
    drain(client)
    assert client.get("/loans/LN-1001", headers=auth("alice")).json()["principal_outstanding"] == "46.00"


def test_successful_payment_applies_waterfall_and_posts_balanced_entry(client):
    ref = new_payment(client, 60).json()["reference"]
    assert webhook(client, "evt-ok", "payment.succeeded", {"reference": ref, "provider_reference": "P1"}) == "applied"
    body = client.get("/loans/LN-1001", headers=auth("alice")).json()
    # 60 paid: fee 1 first, then interest 5, then principal 54 -> outstanding 46
    assert body["fees_due"] == "0.00" and body["interest_due"] == "0.00"
    assert body["principal_outstanding"] == "46.00"
    assert body["payments"][0]["state"] == "SUCCESSFUL"
    t = trial(client)
    assert t["balanced"] is True and t["entry_count"] == 1


def test_duplicate_webhook_deliveries_apply_money_exactly_once(client):
    ref = new_payment(client, 60).json()["reference"]
    data = {"reference": ref, "provider_reference": "P1"}
    statuses = [send_webhook(client, "evt-dup", "payment.succeeded", data).json()["status"] for _ in range(3)]
    assert statuses == ["queued", "duplicate", "duplicate"]
    drain(client)
    body = client.get("/loans/LN-1001", headers=auth("alice")).json()
    assert body["principal_outstanding"] == "46.00"
    assert trial(client)["entry_count"] == 1


def test_different_event_ids_for_same_payment_do_not_double_post(client):
    ref = new_payment(client, 60).json()["reference"]
    data = {"reference": ref, "provider_reference": "P1"}
    assert webhook(client, "evt-a", "payment.succeeded", data) == "applied"
    assert webhook(client, "evt-b", "payment.succeeded", data) == "already_applied"
    assert trial(client)["entry_count"] == 1


def test_failed_payment_can_be_retried_then_succeed(client):
    ref = new_payment(client, 60).json()["reference"]
    assert webhook(client, "evt-f", "payment.failed", {"reference": ref}) == "applied"
    assert client.post(f"/payments/{ref}/retry", headers=auth("alice")).json()["state"] == "PENDING"
    assert webhook(client, "evt-s", "payment.succeeded", {"reference": ref, "provider_reference": "P2"}) == "applied"
    assert trial(client)["balanced"] is True


def test_reversal_restores_balances_and_nets_ledger_to_zero(client):
    ref = new_payment(client, 60).json()["reference"]
    webhook(client, "evt-s", "payment.succeeded", {"reference": ref, "provider_reference": "P1"})
    assert webhook(client, "evt-r", "payment.reversed", {"reference": ref}) == "applied"
    body = client.get("/loans/LN-1001", headers=auth("alice")).json()
    assert body["principal_outstanding"] == "100.00" and body["total_owed"] == "106.00"
    t = trial(client)
    assert t["balanced"] is True
    assert t["accounts"]["payment_clearing"] == "0.00" and t["accounts"]["loan_receivable"] == "0.00"
    assert t["entry_count"] == 2


def test_success_for_a_failed_payment_is_parked_in_suspense(client):
    ref = new_payment(client, 60).json()["reference"]
    webhook(client, "evt-f", "payment.failed", {"reference": ref})
    assert webhook(client, "evt-late", "payment.succeeded",
                   {"reference": ref, "provider_reference": "P9"}) == "needs_review"
    assert client.get("/loans/LN-1001", headers=auth("alice")).json()["principal_outstanding"] == "100.00"
    t = trial(client)
    assert t["balanced"] is True and t["accounts"]["suspense"] == "60.00"


def test_unknown_payment_and_unknown_event_type_are_recorded_not_fatal(client):
    assert webhook(client, "evt-x", "payment.succeeded",
                   {"reference": "PAY-NOPE", "provider_reference": "P"}) == "unknown_payment"
    assert webhook(client, "evt-y", "payment.disputed", {"reference": "PAY-NOPE"}) == "ignored"


def test_transient_failure_is_retried_with_backoff_then_applied(client, db_factory, monkeypatch):
    ref = new_payment(client, 60).json()["reference"]
    send_webhook(client, "evt-flaky", "payment.succeeded", {"reference": ref, "provider_reference": "P1"})
    real = payments_service.apply_event
    calls = {"n": 0}

    def flaky(session, event_type, data):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OperationalError("SELECT 1", {}, Exception("database is temporarily unavailable"))
        return real(session, event_type, data)

    monkeypatch.setattr(payments_service, "apply_event", flaky)
    from datetime import datetime, timedelta, timezone
    first = drain(client)
    assert first["retried"] == 1 and first["processed"] == 0
    # Not due yet: nothing happens until the backoff passes.
    assert drain(client)["claimed"] == 0
    later = datetime.now(timezone.utc) + timedelta(minutes=5)
    summary = payments_service.drain(db_factory, now=later)
    assert summary["processed"] == 1 and summary["results"] == {"applied": 1}
    assert client.get("/loans/LN-1001", headers=auth("alice")).json()["principal_outstanding"] == "46.00"


def test_permanent_failure_is_dead_lettered_not_retried(client, monkeypatch):
    send_webhook(client, "evt-bad", "payment.succeeded", {"reference": "PAY-X"})
    monkeypatch.setattr(payments_service, "apply_event",
                        lambda s, t, d: (_ for _ in ()).throw(ValueError("bad data")))
    summary = drain(client)
    assert summary["dead"] == 1 and summary["retried"] == 0
    dead = client.get("/ops/webhooks?status_filter=dead", headers=auth("ops")).json()
    assert dead[0]["event_id"] == "evt-bad" and "bad data" in dead[0]["last_error"]


def test_repeated_transient_failures_eventually_go_dead(client, db_factory, monkeypatch):
    from datetime import datetime, timedelta, timezone
    ref = new_payment(client, 60).json()["reference"]
    send_webhook(client, "evt-always", "payment.succeeded", {"reference": ref})

    def always_down(s, t, d):
        raise OperationalError("SELECT 1", {}, Exception("down"))

    monkeypatch.setattr(payments_service, "apply_event", always_down)
    now = datetime.now(timezone.utc)
    for i in range(payments_service.MAX_ATTEMPTS):
        payments_service.drain(db_factory, now=now + timedelta(hours=i + 1))
    row = client.get("/ops/webhooks?status_filter=dead", headers=auth("ops")).json()
    assert [r["event_id"] for r in row] == ["evt-always"]
    assert row[0]["attempts"] == payments_service.MAX_ATTEMPTS


def test_malformed_webhook_body_is_rejected_before_storage(client):
    body = json.dumps({"id": "evt-m", "type": "payment.succeeded", "data": "not-an-object"}).encode()
    header = sign_payload(SECRET, body, int(time.time()))
    resp = client.post("/webhooks/payments", content=body, headers={"X-Webhook-Signature": header})
    assert resp.status_code == 422


def test_reconciliation_is_persisted_and_operations_only(client):
    ref = new_payment(client, 60).json()["reference"]
    webhook(client, "evt-s", "payment.succeeded", {"reference": ref, "provider_reference": "P1"})
    assert client.post("/reconciliation/run", json={"settlement": []}, headers=auth("alice")).status_code == 403
    assert client.get("/ledger/integrity", headers=auth("alice")).status_code == 403
    run = client.post("/reconciliation/run", json={"settlement": [
        {"reference": ref, "amount": 60, "status": "settled"},
        {"reference": ref, "amount": 60, "status": "settled"},
    ]}, headers=auth("ops")).json()
    assert run["run_id"] >= 1 and [e["type"] for e in run["exceptions"]] == ["DUPLICATE_SETTLEMENT"]
    stored = client.get(f"/reconciliation/runs/{run['run_id']}", headers=auth("ops")).json()
    assert stored == run
    assert client.get("/reconciliation/runs/99999", headers=auth("ops")).status_code == 404


def test_reconciliation_flags_settled_but_unposted_and_missing_settlement(client):
    ref = new_payment(client, 60).json()["reference"]
    run = client.post("/reconciliation/run", json={"settlement": [
        {"reference": ref, "amount": 60, "status": "settled"}]}, headers=auth("ops")).json()
    assert {e["type"] for e in run["exceptions"]} == {"NOT_POSTED_INTERNALLY"}
    webhook(client, "evt-s", "payment.succeeded", {"reference": ref, "provider_reference": "P1"})
    run2 = client.post("/reconciliation/run", json={"settlement": []}, headers=auth("ops")).json()
    assert {e["type"] for e in run2["exceptions"]} == {"MISSING_SETTLEMENT"}


def test_integrity_is_clean_after_normal_flows(client):
    ref = new_payment(client, 60).json()["reference"]
    webhook(client, "evt-s", "payment.succeeded", {"reference": ref, "provider_reference": "P1"})
    webhook(client, "evt-r", "payment.reversed", {"reference": ref})
    ref2 = new_payment(client, 10, key="key-second-02").json()["reference"]
    webhook(client, "evt-s2", "payment.succeeded", {"reference": ref2, "provider_reference": "P2"})
    report = client.get("/ledger/integrity", headers=auth("ops")).json()
    assert report == {"ok": True, "issue_count": 0, "issues": []}


def test_integrity_detects_tampered_loan_balance(client, db_factory):
    ref = new_payment(client, 60).json()["reference"]
    webhook(client, "evt-s", "payment.succeeded", {"reference": ref, "provider_reference": "P1"})
    with db_factory() as s:
        loan = s.get(LoanAccount, "LN-1001")
        loan.principal_outstanding += 500          # someone edits the balance directly
        s.commit()
    report = client.get("/ledger/integrity", headers=auth("ops")).json()
    assert report["ok"] is False
    assert {i["type"] for i in report["issues"]} == {"LOAN_BALANCE_MISMATCH"}


def test_integrity_detects_a_missing_success_entry(client, db_factory):
    ref = new_payment(client, 60).json()["reference"]
    webhook(client, "evt-s", "payment.succeeded", {"reference": ref, "provider_reference": "P1"})
    with db_factory() as s:
        entry = s.scalar(select(JournalEntry).where(JournalEntry.idempotency_key.like("payment:%:success")))
        for line in list(entry.lines):
            s.delete(line)
        s.delete(entry)
        s.commit()
    kinds = {i["type"] for i in client.get("/ledger/integrity", headers=auth("ops")).json()["issues"]}
    assert "SUCCESSFUL_WITHOUT_ENTRY" in kinds


def test_webhook_events_are_persisted_for_audit(client, db_factory):
    ref = new_payment(client, 60).json()["reference"]
    webhook(client, "evt-audit", "payment.succeeded", {"reference": ref, "provider_reference": "P1"})
    with db_factory() as s:
        ev = s.scalar(select(WebhookEvent).where(WebhookEvent.event_id == "evt-audit"))
        assert ev.status == "PROCESSED" and ev.result == "applied" and "PAY-" in ev.payload
        assert s.scalar(select(Payment).where(Payment.reference == ref)).state == "SUCCESSFUL"
        assert s.scalar(select(JournalEntry).where(JournalEntry.idempotency_key.like("payment:%"))) is not None


@pytest.mark.skipif(not PG_URL, reason="concurrency guarantees need PostgreSQL row locks")
def test_concurrent_workers_apply_one_payment_exactly_once(client, db_factory):
    from concurrent.futures import ThreadPoolExecutor
    ref = new_payment(client, 60).json()["reference"]
    for i in range(6):   # six different deliveries of the same success
        send_webhook(client, f"evt-race-{i}", "payment.succeeded", {"reference": ref, "provider_reference": "P1"})
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(payments_service.drain, db_factory, None, 10) for _ in range(4)]
        for f in futures:
            f.result()
    with db_factory() as s:
        applied = s.scalars(select(JournalEntry).where(JournalEntry.idempotency_key == f"payment:{ref}:success")).all()
        results = s.scalars(select(WebhookEvent.result).where(WebhookEvent.result.isnot(None))).all()
        assert s.scalar(select(Payment.state).where(Payment.reference == ref)) == "SUCCESSFUL"
    assert len(results) == 6
    assert results.count("applied") == 1 and results.count("already_applied") == 5
    assert trial(client)["entry_count"] == 1
    assert len(applied) <= 1


def test_worker_loop_drains_the_inbox_and_stops_when_asked(client, db_factory):
    from app import worker
    ref = new_payment(client, 60).json()["reference"]
    send_webhook(client, "evt-worker", "payment.succeeded", {"reference": ref, "provider_reference": "P1"})
    worker.run_forever(poll_seconds=0, batch_size=10, max_loops=2, factory=db_factory)
    assert client.get("/loans/LN-1001", headers=auth("alice")).json()["principal_outstanding"] == "46.00"


# ---------------------------------------------------------------- overpayments

def _accept_and_settle(client, amount, key, event_id):
    ref = new_payment(client, amount, key=key).json()["reference"]
    webhook(client, event_id, "payment.succeeded", {"reference": ref, "provider_reference": f"P-{event_id}"})
    return ref


def test_overpayment_clears_the_loan_and_keeps_the_excess_as_customer_credit(client):
    # owed 106.00 (fee 1, interest 5, principal 100); paying 110.00 leaves 4.00 credit
    ref = _accept_and_settle(client, 110, "key-over-0002", "evt-over")
    body = client.get("/loans/LN-1001", headers=auth("alice")).json()
    assert body["total_owed"] == "0.00" and body["principal_outstanding"] == "0.00"
    payment = client.get("/loans/LN-1001", headers=auth("alice")).json()["payments"][0]
    assert payment["reference"] == ref and payment["state"] == "SUCCESSFUL"
    assert payment["overpayment_credit"] == "4.00"
    assert payment["applied"] == {"fee": "1.00", "interest": "5.00", "principal": "100.00"}
    accounts = trial(client)["accounts"]
    assert accounts["customer_credit"] == "4.00" and accounts["payment_clearing"] == "110.00"
    assert client.get("/ledger/integrity", headers=auth("ops")).json()["ok"] is True


def test_reversing_an_overpayment_returns_both_the_loan_and_the_credit(client):
    ref = _accept_and_settle(client, 110, "key-over-0003", "evt-over2")
    webhook(client, "evt-over2-rev", "payment.reversed", {"reference": ref})
    body = client.get("/loans/LN-1001", headers=auth("alice")).json()
    assert body["total_owed"] == "106.00"
    assert trial(client)["accounts"]["customer_credit"] == "0.00"
    assert client.get("/ledger/integrity", headers=auth("ops")).json()["ok"] is True


def test_partial_payment_has_no_credit(client):
    _accept_and_settle(client, 50, "key-part-0001", "evt-part")
    payment = client.get("/loans/LN-1001", headers=auth("alice")).json()["payments"][0]
    assert payment["overpayment_credit"] == "0.00"


# ---------------------------------------------------------------- full integrity

def _integrity_kinds(client):
    return {i["type"]: i for i in client.get("/ledger/integrity", headers=auth("ops")).json()["issues"]}


def test_integrity_detects_tampered_interest_balance(client, db_factory):
    _accept_and_settle(client, 60, "key-int-0001", "evt-int")
    with db_factory() as s:
        s.get(LoanAccount, "LN-1001").interest_due += 1
        s.commit()
    issues = _integrity_kinds(client)
    assert set(issues) == {"LOAN_BALANCE_MISMATCH"} and "interest" in issues["LOAN_BALANCE_MISMATCH"]["detail"]


def test_integrity_detects_tampered_fee_balance(client, db_factory):
    _accept_and_settle(client, 60, "key-fee-0001", "evt-fee")
    with db_factory() as s:
        s.get(LoanAccount, "LN-1001").fees_due += 1
        s.commit()
    issues = _integrity_kinds(client)
    assert set(issues) == {"LOAN_BALANCE_MISMATCH"} and "fees" in issues["LOAN_BALANCE_MISMATCH"]["detail"]


def test_integrity_detects_a_posting_that_disagrees_with_the_applied_allocation(client, db_factory):
    _accept_and_settle(client, 60, "key-alloc-001", "evt-alloc")
    with db_factory() as s:
        entry = s.scalar(select(JournalEntry).where(JournalEntry.idempotency_key.like("payment:%:success")))
        interest_line = next(ln for ln in entry.lines if ln.account == "interest_income")
        # move 1.00 from interest to principal, keeping the entry balanced
        interest_line.amount -= 100
        principal_line = next(ln for ln in entry.lines if ln.account == "loan_receivable")
        principal_line.amount += 100
        s.commit()
    kinds = _integrity_kinds(client)
    assert "ALLOCATION_MISMATCH" in kinds
    assert "ENTRY_UNBALANCED" not in kinds and "TRIAL_BALANCE_NOT_ZERO" not in kinds


def test_integrity_detects_an_unbalanced_entry(client, db_factory):
    _accept_and_settle(client, 60, "key-unb-0001", "evt-unb")
    with db_factory() as s:
        entry = s.scalar(select(JournalEntry).where(JournalEntry.idempotency_key.like("payment:%:success")))
        next(ln for ln in entry.lines if ln.account == "fee_income").amount += 7
        s.commit()
    kinds = _integrity_kinds(client)
    assert "ENTRY_UNBALANCED" in kinds and "TRIAL_BALANCE_NOT_ZERO" in kinds


def test_integrity_detects_credit_that_was_recorded_but_not_posted(client, db_factory):
    _accept_and_settle(client, 110, "key-cred-001", "evt-cred")
    with db_factory() as s:
        payment = s.scalar(select(Payment).where(Payment.state == "SUCCESSFUL"))
        payment.credit_applied += 100          # the record claims more credit than the ledger holds
        s.commit()
    kinds = _integrity_kinds(client)
    assert "ALLOCATION_MISMATCH" in kinds and "AMOUNT_NOT_ALLOCATED" in kinds


def test_integrity_detects_a_reversal_that_does_not_net_to_zero(client, db_factory):
    ref = _accept_and_settle(client, 60, "key-rnet-001", "evt-rnet")
    webhook(client, "evt-rnet-rev", "payment.reversed", {"reference": ref})
    assert _integrity_kinds(client) == {}
    with db_factory() as s:
        reversal = s.scalar(select(JournalEntry).where(JournalEntry.idempotency_key.like("payment:%:reversal")))
        for ln in reversal.lines:              # double every line: still balanced, but no longer nets to zero
            ln.amount *= 2
        s.commit()
    kinds = _integrity_kinds(client)
    assert "REVERSAL_NOT_NETTED" in kinds and "ENTRY_UNBALANCED" not in kinds


def test_integrity_flags_applied_amounts_on_a_payment_that_never_succeeded(client, db_factory):
    ref = new_payment(client, 20, key="key-pend-0001").json()["reference"]
    with db_factory() as s:
        s.scalar(select(Payment).where(Payment.reference == ref)).principal_applied = 5
        s.commit()
    assert "APPLIED_WITHOUT_SUCCESS" in _integrity_kinds(client)
