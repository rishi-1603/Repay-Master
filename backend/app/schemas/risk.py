"""Request/response schemas for the /risk/predict endpoint."""
from pydantic import BaseModel, Field


class RiskPredictRequest(BaseModel):
    loan_amount: float = Field(allow_inf_nan=False, gt=0)
    interest_rate: float = Field(allow_inf_nan=False, gt=0, le=100)
    monthly_income: float = Field(allow_inf_nan=False, gt=0)
    monthly_expenses: float = Field(allow_inf_nan=False, ge=0)
    monthly_payment: float = Field(allow_inf_nan=False, gt=0)


class RiskFactor(BaseModel):
    feature: str
    contribution: float


class RiskPredictResponse(BaseModel):
    risk_level: str
    probabilities: dict[str, float]
    top_factors: list[RiskFactor]
    explanation_is_approximate: bool
    model_test_accuracy: float | None = None
