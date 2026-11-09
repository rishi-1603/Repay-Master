"""Loan servicing simulator endpoint: rate changes, holidays, restructuring, extra payments.

All money math is in utils/servicing.py (Decimal). Amounts are returned as
strings so clients never parse them as binary floats.
"""
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.servicing import simulate  # noqa: E402

from app.schemas.servicing import (  # noqa: E402
    ServicingRow,
    ServicingSimulateRequest,
    ServicingSimulateResponse,
)

router = APIRouter(prefix="/loan/servicing", tags=["servicing"])


@router.post("/simulate", response_model=ServicingSimulateResponse)
def simulate_servicing(payload: ServicingSimulateRequest) -> ServicingSimulateResponse:
    try:
        res = simulate(
            payload.principal,
            payload.annual_rate_percent,
            payload.tenure_months,
            payload.start_date,
            rate_changes={c.month: c.annual_rate_percent for c in payload.rate_changes},
            holidays=set(payload.holiday_months),
            extra_payments={e.month: e.amount for e in payload.extra_payments},
            restructures={r.month: r.remaining_months for r in payload.restructures},
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    rows = [
        ServicingRow(
            month=r.month, due_date=r.due_date, kind=r.kind,
            opening=str(r.opening), interest=str(r.interest),
            installment_paid=str(r.installment_paid), principal_paid=str(r.principal_paid),
            extra_paid=str(r.extra_paid), capitalised=str(r.capitalised),
            closing=str(r.closing), event=r.event,
        )
        for r in res.rows
    ]
    return ServicingSimulateResponse(
        months_taken=res.months_taken,
        total_interest=str(res.total_interest),
        total_paid=str(res.total_paid),
        closing_balance=str(res.closing_balance),
        rows=rows,
    )
