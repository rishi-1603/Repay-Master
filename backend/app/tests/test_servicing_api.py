"""API tests for POST /loan/servicing/simulate."""
from decimal import Decimal

BASE = {"principal": 1000000, "annual_rate_percent": 10, "tenure_months": 60,
        "start_date": "2026-01-15"}


def test_baseline_returns_strings_and_closes(client):
    resp = client.post("/loan/servicing/simulate", json=BASE)
    assert resp.status_code == 200
    body = resp.json()
    assert body["months_taken"] == 60
    assert body["closing_balance"] == "0.00"
    assert body["rows"][0]["installment_paid"] == "21247.04"
    assert isinstance(body["total_interest"], str)
    assert Decimal(body["total_paid"]) - Decimal(body["total_interest"]) == Decimal("1000000.00")


def test_all_scenarios_together(client):
    payload = {**BASE, "holiday_months": [2], "rate_changes": [{"month": 13, "annual_rate_percent": 11}],
               "extra_payments": [{"month": 20, "amount": 50000}],
               "restructures": [{"month": 30, "remaining_months": 24}]}
    resp = client.post("/loan/servicing/simulate", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["closing_balance"] == "0.00"
    kinds = [r["kind"] for r in body["rows"]]
    assert kinds[1] == "HOLIDAY"
    assert "restructured" in body["rows"][29]["event"]
    assert "extra 50000.00" in body["rows"][19]["event"]


def test_invalid_scenario_is_422(client):
    resp = client.post("/loan/servicing/simulate", json={**BASE, "holiday_months": [0]})
    assert resp.status_code == 422


def test_nan_principal_is_rejected(client):
    resp = client.post("/loan/servicing/simulate",
                       content=b'{"principal": NaN, "annual_rate_percent": 10, "tenure_months": 12,'
                               b' "start_date": "2026-01-15"}',
                       headers={"Content-Type": "application/json"})
    assert resp.status_code == 422
