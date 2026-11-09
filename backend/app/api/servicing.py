"""Loan servicing endpoints: simulate, foreclosure quote, what-if comparison.

All money math is in utils/servicing.py (Decimal). Amounts are returned as strings,
so clients never parse them as binary floats.
"""
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.servicing import compare_scenarios, foreclosure_quote, simulate  # noqa: E402

from app.schemas.servicing import (  # noqa: E402
    CompareRequest,
    CompareResponse,
    ForeclosureQuoteRequest,
    ForeclosureQuoteResponse,
    ServicingBase,
    ServicingRow,
    ServicingSimulateRequest,
    ServicingSimulateResponse,
)

router = APIRouter(prefix="/loan/servicing", tags=["servicing"])


def _scenario_kwargs(body) -> dict:
    """Translate request lists into the keyword arguments utils/servicing expects."""
    return {
        "holidays": set(body.holiday_months),
        "rate_changes": {c.month: c.annual_rate_percent for c in body.rate_changes},
        "extra_payments": {e.month: e.amount for e in body.extra_payments},
        "partial_payments": {p.month: p.amount_paid for p in body.partial_payments},
        "restructures": {r.month: r.remaining_months for r in body.restructures},
    }


def _base_kwargs(body: ServicingBase) -> dict:
    return {**_scenario_kwargs(body), "late_fee": body.late_fee,
            "processing_fee_pct": body.processing_fee_pct}


def _fail(exc: ValueError):
    raise HTTPException(status_code=422, detail=str(exc))


@router.post("/simulate", response_model=ServicingSimulateResponse)
def simulate_servicing(payload: ServicingSimulateRequest) -> ServicingSimulateResponse:
    try:
        res = simulate(payload.principal, payload.annual_rate_percent, payload.tenure_months,
                       payload.start_date, **_base_kwargs(payload))
    except ValueError as exc:
        _fail(exc)
    rows = [
        ServicingRow(
            month=r.month, due_date=r.due_date, kind=r.kind, opening=str(r.opening),
            interest=str(r.interest), fee_charged=str(r.fee_charged),
            installment_paid=str(r.installment_paid), principal_paid=str(r.principal_paid),
            extra_paid=str(r.extra_paid), closing=str(r.closing), event=r.event,
        )
        for r in res.rows
    ]
    return ServicingSimulateResponse(
        months_taken=res.months_taken, maturity_date=res.maturity_date,
        principal=str(res.principal), total_interest=str(res.total_interest),
        total_late_fees=str(res.total_late_fees), processing_fee=str(res.processing_fee),
        total_paid=str(res.total_paid), total_cost=str(res.total_cost),
        closing_balance=str(res.closing_balance), rows=rows,
    )


@router.post("/foreclosure-quote", response_model=ForeclosureQuoteResponse)
def foreclosure(payload: ForeclosureQuoteRequest) -> ForeclosureQuoteResponse:
    try:
        quote = foreclosure_quote(payload.principal, payload.annual_rate_percent,
                                  payload.tenure_months, payload.start_date, payload.month,
                                  foreclosure_charge_pct=payload.foreclosure_charge_pct,
                                  **_base_kwargs(payload))
    except ValueError as exc:
        _fail(exc)
    return ForeclosureQuoteResponse(**quote)


@router.post("/compare", response_model=CompareResponse)
def compare(payload: CompareRequest) -> CompareResponse:
    names = [s.name for s in payload.scenarios]
    if len(set(names)) != len(names) or "baseline" in names:
        raise HTTPException(status_code=422, detail="scenario names must be unique and not 'baseline'")
    scenarios = {
        s.name: {k: v for k, v in _scenario_kwargs(s).items()}
        for s in payload.scenarios
    }
    # Every scenario inherits the base-level fees.
    for kwargs in scenarios.values():
        kwargs.update(late_fee=payload.late_fee, processing_fee_pct=payload.processing_fee_pct)
    try:
        out = compare_scenarios(payload.principal, payload.annual_rate_percent,
                                payload.tenure_months, payload.start_date, scenarios,
                                horizon_month=payload.horizon_month)
    except ValueError as exc:
        _fail(exc)
    return CompareResponse(scenarios=out)
