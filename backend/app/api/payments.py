"""Loans, payments, signed webhook intake, worker operations, reconciliation and ledger checks.

Auth:
  * loan and payment endpoints: JWT bearer; a user sees only loans they own.
  * /webhooks/payments: no JWT. Authenticated by HMAC signature with a replay window.
  * /ops/*, /reconciliation/*, /ledger/*: role `ops` (admin implies ops) -> 403 otherwise.
  * /ops/webhooks/{event_id}/requeue and /admin/roles/*: role `admin` -> 403 otherwise.
    Roles are granted with `python -m app.cli grant-role`, and checked per request.
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.authz import require_role  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.security import get_current_username  # noqa: E402
from app.db.base import get_db, get_session_factory  # noqa: E402
from app.db.models import JournalEntry, LoanAccount, Payment, ReconciliationRun, WebhookEvent  # noqa: E402
from app.domain.ledger import ACCOUNTS, signed_balance, trial_balance_is_zero  # noqa: E402
from app.domain.money import to_major_str, to_minor  # noqa: E402
from app.domain.payments import InvalidTransition, verify_signature  # noqa: E402
from app.schemas.admin import RoleGrantRequest  # noqa: E402
from app.schemas.payments import LoanCreate, PaymentCreate, ReconRequest  # noqa: E402
from app.services import audit, ledger_service, roles  # noqa: E402
from app.services.ledger_checks import ledger_integrity, persist_reconciliation, run_view  # noqa: E402
from app.services.payments import (  # noqa: E402
    IdempotencyConflict,
    NotFound,
    amount_owed,
    create_intent,
    drain,
    get_owned_loan,
    ingest,
    retry,
)

router = APIRouter(tags=["payments"])
require_ops = require_role("ops")
require_admin = require_role("admin")


def _loan_view(loan: LoanAccount) -> dict:
    return {
        "loan_id": loan.id,
        "principal_original": to_major_str(loan.principal_original),
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
        "overpayment_credit": to_major_str(p.credit_applied),
    }


def _domain_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, IdempotencyConflict):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


# ---------------------------------------------------------------- loans and payments

@router.post("/loans", status_code=201)
def create_loan(payload: LoanCreate, username: str = Depends(get_current_username),
                db: Session = Depends(get_db)) -> dict:
    if db.get(LoanAccount, payload.loan_id) is not None:
        raise HTTPException(status_code=409, detail="loan already exists")
    try:
        principal = to_minor(payload.principal_outstanding)
        if principal <= 0:
            raise ValueError("principal must be positive")
        interest, fees = to_minor(payload.interest_due), to_minor(payload.fees_due)
        loan = LoanAccount(id=payload.loan_id, owner=username, principal_original=principal,
                           principal_outstanding=principal, interest_original=interest, fees_original=fees,
                           interest_due=interest, fees_due=fees)
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
def create_payment(loan_id: str, payload: PaymentCreate, username: str = Depends(get_current_username),
                   db: Session = Depends(get_db)) -> dict:
    try:
        loan = get_owned_loan(db, loan_id, username)
        payment, _created = create_intent(db, loan, to_minor(payload.amount), payload.idempotency_key)
        db.commit()
    except (NotFound, IdempotencyConflict, ValueError) as exc:
        db.rollback()
        raise _domain_error(exc)
    return _payment_view(payment)


@router.post("/payments/{reference}/retry")
def retry_payment(reference: str, username: str = Depends(get_current_username),
                  db: Session = Depends(get_db)) -> dict:
    payment = db.scalar(select(Payment).where(Payment.reference == reference))
    if payment is None:
        raise HTTPException(status_code=404, detail="payment not found")
    get_owned_loan(db, payment.loan_id, username)  # 404 if it is not theirs
    try:
        retry(db, payment)
        db.commit()
    except InvalidTransition as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    return _payment_view(payment)


# ---------------------------------------------------------------- webhooks and worker

@router.post("/webhooks/payments", status_code=202)
async def payment_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    """Verify, store in the inbox, and acknowledge. Processing happens in the worker."""
    secret = settings.PAYMENT_WEBHOOK_SECRET
    if not secret:
        raise HTTPException(status_code=503, detail="webhook secret is not configured")
    body = await request.body()
    if not verify_signature(secret, body, request.headers.get("X-Webhook-Signature"), int(time.time())):
        raise HTTPException(status_code=401, detail="invalid or stale webhook signature")
    try:
        event = json.loads(body)
        event_id, event_type = str(event["id"]), str(event["type"])
        if not isinstance(event["data"], dict):
            raise TypeError("data must be an object")
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=422, detail="malformed webhook body")
    outcome = ingest(db, event_id, event_type, body)
    return {"event_id": event_id, "status": outcome}


@router.post("/ops/webhooks/drain")
def drain_webhooks(limit: int = 50, username: str = Depends(require_ops),
                   factory: sessionmaker = Depends(get_session_factory)) -> dict:
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    return drain(factory, limit=limit)


@router.get("/ops/webhooks")
def list_webhooks(status_filter: str | None = None, username: str = Depends(require_ops),
                  db: Session = Depends(get_db)) -> list[dict]:
    query = select(WebhookEvent).order_by(WebhookEvent.id).limit(200)
    if status_filter:
        query = query.where(WebhookEvent.status == status_filter.upper())
    return [{"event_id": e.event_id, "event_type": e.event_type, "status": e.status,
             "attempts": e.attempts, "result": e.result, "last_error": e.last_error}
            for e in db.scalars(query).all()]


# ---------------------------------------------------------------- reconciliation and ledger

@router.post("/reconciliation/run", status_code=201)
def run_reconciliation(payload: ReconRequest, username: str = Depends(require_ops),
                       db: Session = Depends(get_db)) -> dict:
    """Compare ALL internal payments with a provider settlement report. The run is stored."""
    try:
        settlement = [{"reference": r.reference, "amount": to_minor(r.amount), "status": r.status}
                      for r in payload.settlement]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    run = persist_reconciliation(db, run_by=username, settlement=settlement)
    return run_view(run)


@router.get("/reconciliation/runs/{run_id}")
def read_reconciliation(run_id: int, username: str = Depends(require_ops),
                        db: Session = Depends(get_db)) -> dict:
    run = db.get(ReconciliationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="reconciliation run not found")
    return run_view(run)


@router.get("/ledger/trial-balance")
def trial_balance(username: str = Depends(require_ops), db: Session = Depends(get_db)) -> dict:
    lines = ledger_service.all_lines(db)
    return {
        "balanced": trial_balance_is_zero(lines),
        "entry_count": db.scalar(select(func.count()).select_from(JournalEntry)),
        "accounts": {acct: to_major_str(signed_balance(acct, lines)) for acct in ACCOUNTS},
    }


@router.get("/ledger/integrity")
def integrity(username: str = Depends(require_ops), db: Session = Depends(get_db)) -> dict:
    issues = ledger_integrity(db)
    return {"ok": not issues, "issue_count": len(issues), "issues": issues}


@router.post("/ops/webhooks/{event_id}/requeue")
def requeue_webhook(event_id: str, username: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Put a dead-lettered event back in the queue after a human has fixed its cause."""
    event = db.scalar(select(WebhookEvent).where(WebhookEvent.event_id == event_id).with_for_update())
    if event is None:
        raise HTTPException(status_code=404, detail="webhook event not found")
    if event.status != "DEAD":
        raise HTTPException(status_code=409, detail=f"only DEAD events can be requeued (status is {event.status})")
    event.status, event.attempts, event.next_attempt_at = "RECEIVED", 0, datetime.now(timezone.utc)
    audit.record(db, username, "webhook.requeue", event_id)
    db.commit()
    return {"event_id": event.event_id, "status": event.status, "attempts": event.attempts}


# ---------------------------------------------------------------- role administration

@router.get("/admin/roles/{username}")
def read_roles(username: str, admin: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    return {"username": username, "roles": sorted(roles.granted_roles(db, username))}


@router.post("/admin/roles", status_code=201)
def grant_role(payload: RoleGrantRequest, admin: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    created = roles.grant(db, payload.username, payload.role, actor=admin)
    return {"username": payload.username, "role": payload.role, "created": created}


@router.delete("/admin/roles/{username}/{role}")
def revoke_role(username: str, role: str, admin: str = Depends(require_admin),
                db: Session = Depends(get_db)) -> dict:
    try:
        removed = roles.revoke(db, username, role, actor=admin)
    except roles.UnknownRole as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not removed:
        raise HTTPException(status_code=404, detail="no such role grant")
    return {"username": username, "role": role, "revoked": True}


@router.get("/admin/audit")
def read_audit(limit: int = 100, admin: str = Depends(require_admin), db: Session = Depends(get_db)) -> list[dict]:
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    return [{"id": e.id, "actor": e.actor, "action": e.action, "target": e.target, "detail": e.detail,
             "created_at": e.created_at.isoformat()} for e in audit.recent(db, limit)]
