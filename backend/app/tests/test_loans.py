"""Tests for the deterministic loan-calculation endpoints.

These are the endpoints that must NEVER be handled by an LLM (per the
project's own stated principle -- Gemini explains results, it does not
compute them). Verifying the math here is what actually proves that
principle is followed, rather than just being a README claim.
"""
from utils.finance import calculate_monthly_payment


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_calculate_loan_returns_three_term_options(client):
    response = client.post(
        "/loan/calculate",
        json={
            "loan_amount": 250000,
            "interest_rate": 8.0,
            "monthly_income": 15000,
            "monthly_expenses": 6000,
            "start_date": "2026-01-01",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body["options"].keys()) == {"Short Term", "Recommended", "Long Term"}
    # Short term must have a HIGHER monthly payment than long term (less time to repay).
    assert body["options"]["Short Term"]["monthly_payment"] > body["options"]["Long Term"]["monthly_payment"]
    # Long term must accrue MORE total interest than short term.
    assert body["options"]["Long Term"]["total_interest"] > body["options"]["Short Term"]["total_interest"]


def test_calculate_loan_matches_deterministic_finance_module(client):
    """The API's numbers must be byte-identical to calling utils/finance.py directly --
    this is the actual proof that the API is a thin wrapper, not a reimplementation
    that could silently drift from the underlying financial math."""
    payload = {
        "loan_amount": 500000,
        "interest_rate": 9.5,
        "monthly_income": 40000,
        "monthly_expenses": 12000,
        "start_date": "2026-01-01",
    }
    response = client.post("/loan/calculate", json=payload)
    body = response.json()
    recommended_months = body["options"]["Recommended"]["months"]

    expected_payment = calculate_monthly_payment(payload["loan_amount"], payload["interest_rate"], recommended_months)
    assert abs(body["options"]["Recommended"]["monthly_payment"] - round(expected_payment, 2)) < 0.01


def test_calculate_loan_rejects_expenses_exceeding_income(client):
    response = client.post(
        "/loan/calculate",
        json={
            "loan_amount": 250000,
            "interest_rate": 8.0,
            "monthly_income": 5000,
            "monthly_expenses": 6000,
            "start_date": "2026-01-01",
        },
    )
    assert response.status_code == 422


def test_calculate_loan_rejects_negative_amount(client):
    response = client.post(
        "/loan/calculate",
        json={
            "loan_amount": -100,
            "interest_rate": 8.0,
            "monthly_income": 5000,
            "monthly_expenses": 1000,
            "start_date": "2026-01-01",
        },
    )
    assert response.status_code == 422


def test_calculate_loan_rejects_zero_interest_edge_case_gracefully():
    """0% interest is a real edge case in the amortization math (division by
    r would blow up) -- calculate_monthly_payment has an explicit r==0 branch.
    Exercised directly against the finance module since the API's Pydantic
    schema requires interest_rate > 0, matching real-world loan products."""
    payment = calculate_monthly_payment(120000, 0, 12)
    assert abs(payment - 10000) < 0.01  # no interest -> simple division


def test_prepayment_reduces_months_and_interest(client):
    baseline = client.post(
        "/loan/prepayment",
        json={
            "loan_amount": 250000,
            "interest_rate": 8.0,
            "monthly_income": 15000,
            "monthly_expenses": 6000,
            "start_date": "2026-01-01",
            "months": 96,
            "extra_monthly": 0,
        },
    ).json()
    with_extra = client.post(
        "/loan/prepayment",
        json={
            "loan_amount": 250000,
            "interest_rate": 8.0,
            "monthly_income": 15000,
            "monthly_expenses": 6000,
            "start_date": "2026-01-01",
            "months": 96,
            "extra_monthly": 500,
        },
    ).json()

    assert with_extra["new_months"] < baseline["new_months"]
    assert with_extra["interest_saved"] > 0


def test_prepayment_rejects_lump_sum_month_beyond_tenure(client):
    response = client.post(
        "/loan/prepayment",
        json={
            "loan_amount": 250000,
            "interest_rate": 8.0,
            "monthly_income": 15000,
            "monthly_expenses": 6000,
            "start_date": "2026-01-01",
            "months": 12,
            "lump_sum": 5000,
            "lump_sum_month": 24,
        },
    )
    assert response.status_code == 400
