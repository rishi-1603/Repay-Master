"""Loans, payments, signed payment webhooks, reconciliation and the trial balance.

Auth:
  * loan and payment endpoints: JWT bearer; a user sees only loans they own.
  * /webhooks/payments: no JWT. Authenticated by HMAC signature and a replay window.
  * /reconciliation/run and /ledger/trial-balance: operations only (ADMIN_USERNAMES).
"""
import json
import sys
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import settings  # noqa: E402
from app.core.security import get_current_username  # noqa: E402
from app.db.base import get_db  # noqa: E402
from app.db.models import JournalEntry, LoanAccount, Payment  # noqa: E402
from app.domain.ledger import ACCOUNTS, signed_balance, trial_balance_is_zero  # noqa: E402
from app.domain.money import to_major_str, to_minor  # noqa: E402
from app.domain.payments import InvalidTransition, Overpayment, verify_signature  # noqa: E402
from app.domain.reconciliation import reconcile  # noqa: E402
from app.schemas.payments import LoanCreate, PaymentCreate, ReconRequest  # noqa: E402
from app.services import ledger_service  # noqa: E402
from app.services.payments import (  # noqa: E402
    IdempotencyConflict,
    NotFound,
    amount_owed,
    create_intent,
    get_owned_loan,
    internal_payments_view,
    process_webhook,
    retry,
)

router = APIRouter(tags=["payments"])


def _admins() -> set[str]:
    return {u.strip() for u in settings.ADMIN_USERNAMES.split(",") if u.strip()}


def require_admin(username: str = Depends(get_current_username)) -> str:
    if username not in _admins():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="operations access required")
    return username


def _loan_view(loan: LoanAccount) -> dict:
    return {
        "loan_id": loan.id,
        "principal_outstanding": to_major_str(loan.principal_outstanding),
        "interest_due": to_major_str(loan.interest_due),
        "fees_due": to_major_str(loan.fees_due),
        "total_owed": to_major_str(amount_owed(loan)),
    }


def _payment_view(p: Payment) -> dict:
    return {
        "reference": p.reference,
        "amount": to_major_str(p.amount),
        "state": p.state,
        "idempotency_key": p.idempotency_key,
        "provider_reference": p.provider_reference,
        "applied": {"fee": to_major_str(p.fee_applied), "interest": to_major_str(p.interest_applied),
                    "principal": to_major_str(p.principal_applied)},
    }


def _domain_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, IdempotencyConflict):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.post("/loans", status_code=201)
def create_loan(payload: LoanCreate, username: str = Depends(get_current_username),
                db: Session = Depends(get_db)) -> dict:
    if db.get(LoanAccount, payload.loan_id) is not None:
        raise HTTPException(status_code=409, detail="loan already exists")
    try:
        loan = LoanAccount(id=payload.loan_id, owner=username,
                           principal_outstanding=to_minor(payload.principal_outstanding),
                           interest_due=to_minor(payload.interest_due),
                           fees_due=to_minor(payload.fees_due))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    db.add(loan)
    db.commit()
    return _loan_view(loan)


@router.get("/loans/{loan_id}")
def read_loan(loan_id: str, username: str = Depends(get_current_username),
              db: Session = Depends(get_db)) -> dict:
    try:
        loan = get_owned_loan(db, loan_id, username)
    except NotFound as exc:
        raise _domain_error(exc)
    payments = db.scalars(select(Payment).where(Payment.loan_id == loan_id).order_by(Payment.id)).all()
    return {**_loan_view(loan), "payments": [_payment_view(p) for p in payments]}


@router.post("/loans/{loan_id}/payments", status_code=201)
def create_payment(loan_id: str, payload: PaymentCreate, request: Request,
                   username: str = Depends(get_current_username), db: Session = Depends(get_db)) -> dict:
    try:
        loan = get_owned_loan(db, loan_id, username)
        payment, _created = create_intent(db, loan, to_minor(payload.amount), payload.idempotency_key)
        db.commit()
    except (NotFound, IdempotencyConflict, Overpayment, ValueError) as exc:
        db.rollback()
        raise _domain_error(exc)
    return _payment_view(payment)


@router.post("/payments/{reference}/retry")
def retry_payment(reference: str, username: str = Depends(get_current_username),
                  db: Session = Depends(get_db)) -> dict:
    payment = db.scalar(select(Payment).where(Payment.reference == reference))
    if payment is None:
        raise HTTPException(status_code=404, detail="payment not found")
    get_owned_loan(db, payment.loan_id, username)  # ownership check, 404 if not theirs
    try:
        retry(db, payment)
        db.commit()
    except InvalidTransition as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    return _payment_view(payment)


@router.post("/webhooks/payments", status_code=200)
async def payment_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    secret = settings.PAYMENT_WEBHOOK_SECRET
    if not secret:
        raise HTTPException(status_code=503, detail="webhook secret is not configured")
    body = await request.body()
    if not verify_signature(secret, body, request.headers.get("X-Webhook-Signature"), int(time.time())):
        raise HTTPException(status_code=401, detail="invalid or stale webhook signature")
    try:
        event = json.loads(body)
        event_id, event_type, data = event["id"], event["type"], event["data"]
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=422, detail="malformed webhook body")
    result = process_webhook(db, str(event_id), str(event_type), data, body)
    return {"event_id": str(event_id), "result": result}


@router.post("/reconciliation/run")
def run_reconciliation(payload: ReconRequest, username: str = Depends(require_admin),
                       db: Session = Depends(get_db)) -> dict:
    """Operations view: compares ALL internal payments with the provider's settlement report."""
    internal = internal_payments_view(db)
    try:
        settlement = [{"reference": r.reference, "amount": to_minor(r.amount), "status": r.status}
                      for r in payload.settlement]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    exceptions = reconcile(internal, settlement)
    return {"checked_internal": len(internal), "checked_settlement": len(settlement),
            "exception_count": len(exceptions), "exceptions": exceptions}


@router.get("/ledger/trial-balance")
def trial_balance(username: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    lines = ledger_service.all_lines(db)
    return {
        "balanced": trial_balance_is_zero(lines),
        "entry_count": db.scalar(select(func.count()).select_from(JournalEntry)),
        "accounts": {acct: to_major_str(signed_balance(acct, lines)) for acct in ACCOUNTS},
    }
