"""Loan calculation endpoints.

Deliberately deterministic: all math here comes straight from
`utils/finance.py` (the same module the Streamlit app already used). No LLM
is involved in computing money -- see app/api/ai.py (Day 2) for where Gemini
is used instead, strictly for natural-language explanation of results that
were already computed here.
"""
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException

# utils/ lives at the repo root (sibling of backend/), not inside backend/.
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.finance import (  # noqa: E402
    calculate_affordability,
    calculate_monthly_payment,
    simulate_prepayment,
    suggest_repayment_period,
)
from app.schemas.loan import (
    AffordabilityBreakdown,
    LoanCalculateRequest,
    LoanCalculateResponse,
    PrepaymentRequest,
    PrepaymentResponse,
    RepaymentOption,
)

router = APIRouter(prefix="/loan", tags=["loan"])

# Matches the Short / Recommended / Long term multipliers already used by the
# Streamlit UI, kept here so the API produces the same three options.
_TERM_MULTIPLIERS = {"Short Term": 0.7, "Recommended": 1.0, "Long Term": 1.5}
_MIN_MONTHS = 6
_MAX_MONTHS = 480


@router.post("/calculate", response_model=LoanCalculateResponse)
def calculate_loan(payload: LoanCalculateRequest) -> LoanCalculateResponse:
    suggested_months = suggest_repayment_period(
        payload.loan_amount, payload.monthly_income, payload.monthly_expenses, payload.interest_rate
    )

    options: dict[str, RepaymentOption] = {}
    for term_name, multiplier in _TERM_MULTIPLIERS.items():
        months = max(_MIN_MONTHS, min(_MAX_MONTHS, round(suggested_months * multiplier)))
        monthly_payment = calculate_monthly_payment(payload.loan_amount, payload.interest_rate, months)
        total_paid = monthly_payment * months
        total_interest = total_paid - payload.loan_amount
        options[term_name] = RepaymentOption(
            months=months,
            monthly_payment=round(monthly_payment, 2),
            total_interest=round(total_interest, 2),
            total_paid=round(total_paid, 2),
        )

    recommended_payment = options["Recommended"].monthly_payment
    affordability = calculate_affordability(recommended_payment, payload.monthly_income, payload.monthly_expenses)

    return LoanCalculateResponse(
        suggested_months=suggested_months,
        options=options,
        affordability=AffordabilityBreakdown(**affordability),
    )


@router.post("/prepayment", response_model=PrepaymentResponse)
def simulate_prepayment_endpoint(payload: PrepaymentRequest) -> PrepaymentResponse:
    if payload.lump_sum_month is not None and payload.lump_sum_month > payload.months:
        raise HTTPException(status_code=400, detail="lump_sum_month cannot be greater than months.")

    result = simulate_prepayment(
        loan_amount=payload.loan_amount,
        interest_rate=payload.interest_rate,
        months=payload.months,
        start_date=payload.start_date,
        extra_monthly=payload.extra_monthly,
        lump_sum=payload.lump_sum,
        lump_sum_month=payload.lump_sum_month,
    )

    return PrepaymentResponse(
        baseline_months=result["baseline_months"],
        new_months=result["new_months"],
        months_saved=result["months_saved"],
        baseline_interest=round(result["baseline_interest"], 2),
        new_interest=round(result["new_interest"], 2),
        interest_saved=round(result["interest_saved"], 2),
    )
