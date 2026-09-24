"""ML risk-prediction endpoint: wraps the existing RandomForest + SHAP pipeline
from utils/risk.py behind a real HTTP API instead of only being reachable
from inside the Streamlit process.
"""
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.risk import explain_prediction, load_model_metrics, load_risk_model, predict_risk  # noqa: E402

from app.schemas.risk import RiskFactor, RiskPredictRequest, RiskPredictResponse  # noqa: E402

router = APIRouter(prefix="/risk", tags=["risk"])


@router.post("/predict", response_model=RiskPredictResponse)
def predict(payload: RiskPredictRequest) -> RiskPredictResponse:
    features = {
        "loan_amount": payload.loan_amount,
        "interest_rate": payload.interest_rate,
        "monthly_income": payload.monthly_income,
        "monthly_expenses": payload.monthly_expenses,
        "monthly_payment": payload.monthly_payment,
    }

    try:
        model, scaler = load_risk_model()
    except FileNotFoundError as exc:
        # A missing model artifact is a deployment/setup problem, not a client
        # error -- 503 (Service Unavailable) is the correct status, not 500.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    label, proba_dict = predict_risk(model, scaler, features)
    explain_df = explain_prediction(model, scaler, features)
    is_approximate = bool(explain_df["approximate"].iloc[0]) if len(explain_df) else True

    top_factors = [
        RiskFactor(feature=row["feature"], contribution=round(float(row["contribution"]), 4))
        for _, row in explain_df.head(5).iterrows()
    ]

    metrics = load_model_metrics()

    return RiskPredictResponse(
        risk_level=str(label),
        probabilities={str(k): round(float(v), 4) for k, v in proba_dict.items()},
        top_factors=top_factors,
        explanation_is_approximate=is_approximate,
        model_test_accuracy=metrics.get("test_accuracy"),
    )
