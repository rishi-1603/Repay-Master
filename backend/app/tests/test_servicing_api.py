"""API tests for the loan servicing endpoints."""
from decimal import Decimal

BASE = {"principal": 1000000, "annual_rate_percent": 10, "tenure_months": 60,
        "start_date": "2026-01-15"}


def test_simulate_baseline_returns_strings_and_closes(client):
    body = client.post("/loan/servicing/simulate", json=BASE).json()
    assert body["months_taken"] == 60
    assert body["closing_balance"] == "0.00"
    assert body["rows"][0]["installment_paid"] == "21247.04"
    assert body["maturity_date"] == "2031-01-15"
    assert Decimal(body["total_paid"]) == Decimal("1000000") + Decimal(body["total_interest"])


def test_simulate_with_every_scenario_type(client):
    payload = {**BASE, "holiday_months": [2],
               "rate_changes": [{"month": 13, "annual_rate_percent": 11}],
               "extra_payments": [{"month": 20, "amount": 50000}],
               "partial_payments": [{"month": 30, "amount_paid": 5000}],
               "restructures": [{"month": 40, "remaining_months": 12}],
               "late_fee": 500, "processing_fee_pct": 1}
    resp = client.post("/loan/servicing/simulate", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["closing_balance"] == "0.00"
    assert body["rows"][1]["kind"] == "HOLIDAY"
    assert "rate->" in body["rows"][12]["event"]
    assert "extra 50000.00" in body["rows"][19]["event"]
    assert "late fee 500.00" in body["rows"][29]["event"]
    assert body["processing_fee"] == "10000.00"


def test_foreclosure_quote_endpoint(client):
    resp = client.post("/loan/servicing/foreclosure-quote",
                       json={**BASE, "month": 1, "foreclosure_charge_pct": 2})
    assert resp.status_code == 200
    assert resp.json()["total_payable"] == "1028333.33"


def test_foreclosure_quote_after_closure_is_422(client):
    resp = client.post("/loan/servicing/foreclosure-quote", json={**BASE, "month": 99})
    assert resp.status_code == 422


def test_compare_endpoint_returns_each_scenario(client):
    payload = {**BASE, "horizon_month": 12, "scenarios": [
        {"name": "extra_2000", "extra_payments": [{"month": m, "amount": 2000} for m in range(1, 61)]},
        {"name": "defer_six", "holiday_months": [1, 2, 3, 4, 5, 6]},
    ]}
    resp = client.post("/loan/servicing/compare", json=payload)
    assert resp.status_code == 200
    scenarios = resp.json()["scenarios"]
    assert set(scenarios) == {"baseline", "extra_2000", "defer_six"}
    assert scenarios["extra_2000"]["months_saved_vs_baseline"] > 0
    assert scenarios["defer_six"]["months_saved_vs_baseline"] < 0


def test_compare_rejects_base_level_changes(client):
    resp = client.post("/loan/servicing/compare",
                       json={**BASE, "holiday_months": [2],
                             "scenarios": [{"name": "x"}]})
    assert resp.status_code == 422


def test_compare_rejects_duplicate_or_baseline_names(client):
    dup = client.post("/loan/servicing/compare",
                      json={**BASE, "scenarios": [{"name": "a"}, {"name": "a"}]})
    assert dup.status_code == 422
    reserved = client.post("/loan/servicing/compare",
                           json={**BASE, "scenarios": [{"name": "baseline"}]})
    assert reserved.status_code == 422


def test_invalid_holiday_month_is_422(client):
    assert client.post("/loan/servicing/simulate",
                       json={**BASE, "holiday_months": [0]}).status_code == 422


def test_nan_principal_is_rejected(client):
    resp = client.post("/loan/servicing/simulate",
                       content=b'{"principal": NaN, "annual_rate_percent": 10, "tenure_months": 12,'
                               b' "start_date": "2026-01-15"}',
                       headers={"Content-Type": "application/json"})
    assert resp.status_code == 422
