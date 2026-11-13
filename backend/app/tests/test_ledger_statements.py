"""Loan ledger, statements and arrears against PostgreSQL.

Requires DATABASE_URL to point at a PostgreSQL test database, e.g.
  DATABASE_URL=postgresql+psycopg://rm@127.0.0.1:5432/repaymaster_pytest PGPASSWORD=...
The fixture creates the schema and empties the ledger tables before each test.
"""
import threading
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.db.base import Base, get_engine, session_factory
from app.services import ledger
from app.tests.conftest import auth_headers, register_and_login


@pytest.fixture(autouse=True)
def clean_ledger():
    engine = get_engine(settings.DATABASE_URL)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE loan_journal, loan_accounts RESTART IDENTITY CASCADE"))
    yield


def _create_loan(client, token, principal="1000.00", due=None, opened="2026-06-01"):
    body = {"principal": principal, "opened_on": opened}
    if due is not None:
        body["due_date"] = due
    r = client.post("/ledger/loans", json=body, headers=auth_headers(token))
    assert r.status_code == 201, r.text
    return r.json()


def test_new_loan_statement_opens_and_closes_at_principal(client):
    token = register_and_login(client)
    loan = _create_loan(client, token)
    r = client.get(f"/ledger/loans/{loan['id']}/statement", headers=auth_headers(token))
    body = r.json()
    assert r.status_code == 200
    assert body["opening_balance"] == "1000.00"
    assert body["closing_balance"] == "1000.00"
    assert body["lines"] == []
    assert body["reconciles_with_loan_balance"] is True


def test_repayment_then_reversal_restores_balance(client):
    token = register_and_login(client)
    loan = _create_loan(client, token)
    h = auth_headers(token)
    rep = client.post(f"/ledger/loans/{loan['id']}/repayments", json={"amount": "250.00", "posted_on": "2026-07-01"}, headers=h)
    assert rep.status_code == 201
    assert client.get(f"/ledger/loans/{loan['id']}", headers=h).json()["balance"] == "750.00"

    rev = client.post(f"/ledger/repayments/{rep.json()['id']}/reverse", headers=h)
    assert rev.status_code == 201
    assert rev.json()["kind"] == "reversal"
    assert client.get(f"/ledger/loans/{loan['id']}", headers=h).json()["balance"] == "1000.00"


def test_overpayment_is_refused_and_leaves_balance_untouched(client):
    token = register_and_login(client)
    loan = _create_loan(client, token, principal="100.00")
    h = auth_headers(token)
    r = client.post(f"/ledger/loans/{loan['id']}/repayments", json={"amount": "100.01"}, headers=h)
    assert r.status_code == 409
    assert client.get(f"/ledger/loans/{loan['id']}", headers=h).json()["balance"] == "100.00"


@pytest.mark.parametrize("amount", ["0", "-5.00", "1.001"])
def test_non_positive_or_over_precise_amounts_are_rejected(client, amount):
    token = register_and_login(client)
    loan = _create_loan(client, token)
    r = client.post(f"/ledger/loans/{loan['id']}/repayments", json={"amount": amount}, headers=auth_headers(token))
    assert r.status_code == 422


def test_a_repayment_cannot_be_reversed_twice_or_reversed_itself(client):
    token = register_and_login(client)
    loan = _create_loan(client, token)
    h = auth_headers(token)
    rep = client.post(f"/ledger/loans/{loan['id']}/repayments", json={"amount": "50.00"}, headers=h).json()
    first = client.post(f"/ledger/repayments/{rep['id']}/reverse", headers=h)
    assert first.status_code == 201
    assert client.post(f"/ledger/repayments/{rep['id']}/reverse", headers=h).status_code == 409
    assert client.post(f"/ledger/repayments/{first.json()['id']}/reverse", headers=h).status_code == 409


def test_other_users_cannot_see_or_change_a_loan(client):
    owner = register_and_login(client, username="owner1")
    other = register_and_login(client, username="intruder1")
    loan = _create_loan(client, owner)
    lid = loan["id"]
    oh = auth_headers(other)
    assert client.get(f"/ledger/loans/{lid}", headers=oh).status_code == 404
    assert client.get(f"/ledger/loans/{lid}/statement", headers=oh).status_code == 404
    assert client.post(f"/ledger/loans/{lid}/repayments", json={"amount": "1.00"}, headers=oh).status_code == 404
    assert client.put(f"/ledger/loans/{lid}/due-date", json={"due_date": "2026-01-01"}, headers=oh).status_code == 404


def test_statement_period_folds_earlier_postings_into_the_opening_balance(client):
    token = register_and_login(client)
    loan = _create_loan(client, token, principal="1000.00")
    h = auth_headers(token)
    lid = loan["id"]
    client.post(f"/ledger/loans/{lid}/repayments", json={"amount": "100.00", "posted_on": "2026-07-05"}, headers=h)
    client.post(f"/ledger/loans/{lid}/repayments", json={"amount": "200.00", "posted_on": "2026-08-10"}, headers=h)
    client.post(f"/ledger/loans/{lid}/repayments", json={"amount": "300.00", "posted_on": "2026-09-15"}, headers=h)

    body = client.get(f"/ledger/loans/{lid}/statement", params={"from": "2026-08-01", "to": "2026-08-31"}, headers=h).json()
    assert body["opening_balance"] == "900.00"
    assert [line["amount"] for line in body["lines"]] == ["200.00"]
    assert body["closing_balance"] == "700.00"
    assert body["reconciles_with_loan_balance"] is None  # only a full statement can be checked against the balance


def test_statement_rejects_inverted_period(client):
    token = register_and_login(client)
    loan = _create_loan(client, token)
    r = client.get(f"/ledger/loans/{loan['id']}/statement", params={"from": "2026-09-01", "to": "2026-08-01"}, headers=auth_headers(token))
    assert r.status_code == 422


def test_full_statement_reconciles_after_mixed_postings(client):
    token = register_and_login(client)
    loan = _create_loan(client, token, principal="500.00")
    h = auth_headers(token)
    lid = loan["id"]
    a = client.post(f"/ledger/loans/{lid}/repayments", json={"amount": "120.50", "posted_on": "2026-07-01"}, headers=h).json()
    client.post(f"/ledger/loans/{lid}/repayments", json={"amount": "80.25", "posted_on": "2026-07-09"}, headers=h)
    client.post(f"/ledger/repayments/{a['id']}/reverse", headers=h)
    body = client.get(f"/ledger/loans/{lid}/statement", headers=h).json()
    assert body["closing_balance"] == client.get(f"/ledger/loans/{lid}", headers=h).json()["balance"]
    assert body["reconciles_with_loan_balance"] is True
    assert [line["effect"] for line in body["lines"]] == ["-120.50", "-80.25", "+120.50"]


def test_concurrent_repayments_cannot_both_pass_the_balance_check(client):
    """Two payers race for the last 100.00. Row locking must let exactly one through."""
    token = register_and_login(client)
    loan = _create_loan(client, token, principal="100.00")
    owner = "alice"  # register_and_login's default username
    factory = session_factory()
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def pay():
        db = factory()
        try:
            barrier.wait()
            ledger.post_repayment(db, owner, loan["id"], Decimal("100.00"), date(2026, 7, 1))
            outcomes.append("ok")
        except ledger.Conflict:
            outcomes.append("conflict")
        finally:
            db.close()

    threads = [threading.Thread(target=pay) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(outcomes) == ["conflict", "ok"]
    assert client.get(f"/ledger/loans/{loan['id']}", headers=auth_headers(token)).json()["balance"] == "0.00"


def test_due_date_change_moves_the_loan_between_buckets(client):
    token = register_and_login(client)
    h = auth_headers(token)
    loan = _create_loan(client, token, due=None)
    assert loan["delinquency_bucket"] == "unscheduled"
    r = client.put(f"/ledger/loans/{loan['id']}/due-date", json={"due_date": "2000-01-01"}, headers=h)
    assert r.status_code == 200
    assert r.json()["delinquency_bucket"] == "90+"
    assert r.json()["days_past_due"] > 90


def test_delinquency_report_groups_loans_and_excludes_closed_ones(client):
    token = register_and_login(client)
    h = auth_headers(token)
    _create_loan(client, token, principal="100.00", due="2026-09-30")   # not yet due
    _create_loan(client, token, principal="200.00", due="2026-09-03")   # 20 days late
    _create_loan(client, token, principal="300.00", due="2026-07-01")   # 61-90 days late
    closed = _create_loan(client, token, principal="50.00", due="2020-01-01")
    client.post(f"/ledger/loans/{closed['id']}/repayments", json={"amount": "50.00"}, headers=h)
    _create_loan(client, token, principal="75.00", due=None)            # unscheduled

    body = client.get("/ledger/delinquency", params={"as_of": "2026-09-23"}, headers=h).json()
    assert body["buckets"]["current"] == {"count": 1, "balance": "100.00"}
    assert body["buckets"]["1-30"] == {"count": 1, "balance": "200.00"}
    assert body["buckets"]["61-90"] == {"count": 1, "balance": "300.00"}
    assert body["buckets"]["90+"] == {"count": 0, "balance": "0.00"}
    assert body["buckets"]["closed"] == {"count": 1, "balance": "0.00"}
    assert body["buckets"]["unscheduled"] == {"count": 1, "balance": "75.00"}
    arrears = sorted((row["bucket"], row["days_past_due"]) for row in body["overdue_loans"])
    assert arrears == [("1-30", 20), ("61-90", 84)]


def test_delinquency_report_is_owner_scoped(client):
    a = register_and_login(client, username="ledger-a")
    b = register_and_login(client, username="ledger-b")
    _create_loan(client, a, principal="999.00", due="2020-01-01")
    body = client.get("/ledger/delinquency", params={"as_of": "2026-09-23"}, headers=auth_headers(b)).json()
    assert body["buckets"]["90+"]["count"] == 0
    assert body["overdue_loans"] == []
