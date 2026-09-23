"""Request/response schemas for loan calculation and prepayment simulation."""
from datetime import date

from pydantic import BaseModel, Field, field_validator


class LoanCalculateRequest(BaseModel):
    loan_amount: float = Field(gt=0, description="Principal loan amount.")
    interest_rate: float = Field(gt=0, le=100, description="Annual interest rate, percent (e.g. 8.5).")
    monthly_income: float = Field(gt=0)
    monthly_expenses: float = Field(ge=0)
    start_date: date = Field(default_factory=date.today)

    @field_validator("monthly_expenses")
    @classmethod
    def expenses_not_greater_than_income(cls, v: float, info) -> float:
        income = info.data.get("monthly_income")
        if income is not None and v > income:
            raise ValueError("monthly_expenses cannot exceed monthly_income.")
        return v


class RepaymentOption(BaseModel):
    months: int
    monthly_payment: float
    total_interest: float
    total_paid: float


class AffordabilityBreakdown(BaseModel):
    dti_ratio: float
    total_burden: float
    savings_potential: float
    affordability_score: int


class LoanCalculateResponse(BaseModel):
    suggested_months: int
    options: dict[str, RepaymentOption]
    affordability: AffordabilityBreakdown


class PrepaymentRequest(LoanCalculateRequest):
    months: int = Field(gt=0, le=720, description="Loan tenure in months for the baseline schedule.")
    extra_monthly: float = Field(default=0, ge=0)
    lump_sum: float = Field(default=0, ge=0)
    lump_sum_month: int | None = Field(default=None, gt=0)


class PrepaymentResponse(BaseModel):
    baseline_months: int
    new_months: int
    months_saved: int
    baseline_interest: float
    new_interest: float
    interest_saved: float
