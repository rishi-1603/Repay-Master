"""Tests for the ML risk-prediction endpoint.

Verifies the API actually calls the real RandomForest + SHAP pipeline
(utils/risk.py) end-to-end, not a stub -- and that a missing model artifact
degrades to a proper 503 rather than an unhandled 500.
"""
from unittest.mock import patch


def test_predict_risk_returns_valid_response(client):
    response = client.post(
        "/risk/predict",
        json={
            "loan_amount": 250000,
            "interest_rate": 8.0,
            "monthly_income": 15000,
            "monthly_expenses": 6000,
            "monthly_payment": 3200,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["risk_level"] in {"Low", "Medium", "High"}
    assert abs(sum(body["probabilities"].values()) - 1.0) < 0.01
    assert len(body["top_factors"]) > 0
    assert body["model_test_accuracy"] is not None


def test_predict_risk_top_factors_are_sorted_by_absolute_contribution(client):
    response = client.post(
        "/risk/predict",
        json={
            "loan_amount": 500000,
            "interest_rate": 12.0,
            "monthly_income": 20000,
            "monthly_expenses": 15000,
            "monthly_payment": 7000,
        },
    )
    factors = response.json()["top_factors"]
    contributions = [abs(f["contribution"]) for f in factors]
    assert contributions == sorted(contributions, reverse=True)


def test_predict_risk_rejects_zero_income(client):
    response = client.post(
        "/risk/predict",
        json={
            "loan_amount": 250000,
            "interest_rate": 8.0,
            "monthly_income": 0,
            "monthly_expenses": 0,
            "monthly_payment": 3200,
        },
    )
    assert response.status_code == 422


def test_predict_risk_returns_503_when_model_artifacts_missing(client):
    """Simulates a real deployment failure mode: someone deploys the API
    without ever running `python train_model.py`. This must be a clean 503,
    not a raw stack-trace 500 -- proves the FileNotFoundError handling in
    app/api/risk.py actually works rather than just being unreachable code."""
    with patch("app.api.risk.load_risk_model", side_effect=FileNotFoundError("model not found")):
        response = client.post(
            "/risk/predict",
            json={
                "loan_amount": 250000,
                "interest_rate": 8.0,
                "monthly_income": 15000,
                "monthly_expenses": 6000,
                "monthly_payment": 3200,
            },
        )
    assert response.status_code == 503
