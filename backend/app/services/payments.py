"""Payment intents, webhook ingestion, event application and the retry-safe worker.

Flow for a provider webhook:
  1. ingest():   store the verified event in the inbox (status RECEIVED), return 202.
  2. drain():    a worker claims pending events one at a time (row lock, SKIP LOCKED on
                 PostgreSQL), applies them, and marks them PROCESSED.
                 Transient failures are retried with exponential backoff; events that keep
                 failing, or are malformed, go to DEAD for a human.

Idempotency layers, in order:
  * webhook_events.event_id unique: a redelivered webhook is stored once.
  * payments(loan_id, idempotency_key) unique: a retried payment intent is created once.
  * journal_entries.idempotency_key unique: a payment's money moves at most once.
  * Row locks on the payment and loan rows serialise concurrent workers on PostgreSQL.

An overpayment is accepted. The waterfall takes what is owed; the excess is credited to the
customer (customer_credit) and recorded on the payment, so the money is never lost or refused.
"""
import json
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import JournalEntry, LoanAccount, Payment, WebhookEvent
from app.domain.ledger import Line, repayment_lines, reversal_lines
from app.domain.payments import InvalidTransition, PaymentState, allocate, transition
from app.services.ledger_service import post_entry

ACTIVE = ("RECEIVED", "RETRY")
MAX_ATTEMPTS = 5
# Errors that will never succeed on retry: malformed payloads and bad data.
PERMANENT_ERRORS = (ValueError, KeyError, TypeError)


class IdempotencyConflict(ValueError):
    pass


class NotFound(LookupError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_owned_loan(session: Session, loan_id: str, owner: str) -> LoanAccount:
    loan = session.get(LoanAccount, loan_id)
    if loan is None or loan.owner != owner:
        raise NotFound(f"loan {loan_id} not found")   # same answer whether it exists or not
    return loan


def amount_owed(loan: LoanAccount) -> int:
    return loan.fees_due + loan.interest_due + loan.principal_outstanding


# ---------------------------------------------------------------- payment intents

def create_intent(session: Session, loan: LoanAccount, amount: int, idempotency_key: str) -> tuple[Payment, bool]:
    """Returns (payment, created). Same key and amount: the original payment. Same key, other amount: conflict."""
    existing = session.scalar(select(Payment).where(
        Payment.loan_id == loan.id, Payment.idempotency_key == idempotency_key))
    if existing is not None:
        if existing.amount != amount:
            raise IdempotencyConflict("idempotency key was already used for a different amount")
        return existing, False
    payment = Payment(loan_id=loan.id, idempotency_key=idempotency_key,
                      reference=f"PAY-{secrets.token_hex(8).upper()}", amount=amount,
                      state=PaymentState.INITIATED.value)
    session.add(payment)
    payment.state = transition(PaymentState.INITIATED, PaymentState.PENDING).value
    session.flush()
    return payment, True


def retry(session: Session, payment: Payment) -> Payment:
    payment.state = transition(PaymentState(payment.state), PaymentState.PENDING).value
    session.flush()
    return payment


# ---------------------------------------------------------------- applying events

def _post_suspense(session: Session, key: str, amount: int, description: str) -> None:
    post_entry(session, key, description, [Line("payment_clearing", "D", amount),
                                           Line("suspense", "C", amount)])


def _apply_success(session: Session, payment: Payment, provider_reference: str | None) -> str:
    loan = session.get(LoanAccount, payment.loan_id, with_for_update=True)
    try:
        transition(PaymentState(payment.state), PaymentState.SUCCESSFUL)
        fee, interest, principal, credit = allocate(payment.amount, loan.fees_due, loan.interest_due,
                                                    loan.principal_outstanding)
    except InvalidTransition as exc:
        _post_suspense(session, f"payment:{payment.id}:suspense", payment.amount,
                       f"unapplied receipt {payment.reference}: {exc}")
        return "needs_review"
    payment.state = PaymentState.SUCCESSFUL.value
    payment.provider_reference = provider_reference or payment.provider_reference
    payment.fee_applied, payment.interest_applied, payment.principal_applied = fee, interest, principal
    payment.credit_applied = credit
    loan.fees_due -= fee
    loan.interest_due -= interest
    loan.principal_outstanding -= principal
    post_entry(session, f"payment:{payment.id}:success", f"repayment {payment.reference}",
               repayment_lines(payment.amount, principal, interest, fee, credit))
    return "applied"


def _apply_failure(session: Session, payment: Payment) -> str:
    payment.state = transition(PaymentState(payment.state), PaymentState.FAILED).value
    return "applied"


def _apply_reversal(session: Session, payment: Payment) -> str:
    payment.state = transition(PaymentState(payment.state), PaymentState.REVERSED).value
    loan = session.get(LoanAccount, payment.loan_id, with_for_update=True)
    loan.fees_due += payment.fee_applied
    loan.interest_due += payment.interest_applied
    loan.principal_outstanding += payment.principal_applied
    original = session.scalar(select(JournalEntry).where(
        JournalEntry.idempotency_key == f"payment:{payment.id}:success"))
    if original is not None:
        lines = [Line(ln.account, ln.side, ln.amount) for ln in original.lines]
        post_entry(session, f"payment:{payment.id}:reversal", f"reversal {payment.reference}",
                   reversal_lines(lines), reverses_entry_id=original.id)
    return "applied"


ACTIONS = {"payment.succeeded": "success", "payment.failed": "failed", "payment.reversed": "reversed"}


def apply_event(session: Session, event_type: str, data: dict) -> str:
    """Apply one provider event inside the caller's transaction. Does not commit."""
    action = ACTIONS.get(event_type)
    if action is None:
        return "ignored"
    payment = session.scalar(select(Payment).where(Payment.reference == data.get("reference")).with_for_update())
    if payment is None:
        return "unknown_payment"
    if action == "success":
        if payment.state == PaymentState.SUCCESSFUL.value:
            return "already_applied"
        return _apply_success(session, payment, data.get("provider_reference"))
    if action == "failed":
        if payment.state == PaymentState.FAILED.value:
            return "already_applied"
        return _apply_failure(session, payment)
    if payment.state == PaymentState.REVERSED.value:
        return "already_applied"
    return _apply_reversal(session, payment)


# ---------------------------------------------------------------- inbox and worker

def ingest(session: Session, event_id: str, event_type: str, raw_body: bytes, now: datetime | None = None) -> str:
    """Store a verified webhook for later processing. Returns 'queued' or 'duplicate'."""
    now = now or _utcnow()
    session.add(WebhookEvent(event_id=event_id, event_type=event_type,
                             payload=raw_body.decode("utf-8", "replace"), status="RECEIVED",
                             attempts=0, next_attempt_at=now, received_at=now))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return "duplicate"
    return "queued"


def drain(session_factory, now: datetime | None = None, limit: int = 50) -> dict:
    """Process up to `limit` due events, one transaction each. Safe to run from many workers.

    Each event is locked (SKIP LOCKED where supported), applied, and marked in the same
    transaction. A failure rolls that transaction back and records the attempt separately.
    """
    now = now or _utcnow()
    with session_factory() as s:
        due_ids = s.scalars(select(WebhookEvent.id).where(
            WebhookEvent.status.in_(ACTIVE), WebhookEvent.next_attempt_at <= now
        ).order_by(WebhookEvent.id).limit(limit)).all()

    summary = {"claimed": len(due_ids), "processed": 0, "retried": 0, "dead": 0, "results": {}}
    for event_pk in due_ids:
        s = session_factory()
        try:
            event = s.scalar(select(WebhookEvent).where(
                WebhookEvent.id == event_pk, WebhookEvent.status.in_(ACTIVE),
                WebhookEvent.next_attempt_at <= now).with_for_update(skip_locked=True))
            if event is None:
                s.rollback()          # another worker has it, or it changed state
                continue
            data = json.loads(event.payload)["data"]
            result = apply_event(s, event.event_type, data)
            event.status, event.result, event.processed_at = "PROCESSED", result, now
            event.last_error = None
            s.commit()
            summary["processed"] += 1
            summary["results"][result] = summary["results"].get(result, 0) + 1
        except Exception as exc:  # noqa: BLE001  (every failure must be recorded, never lost)
            s.rollback()
            _record_failure(session_factory, event_pk, exc, now, summary)
        finally:
            s.close()
    return summary


def _record_failure(session_factory, event_pk: int, exc: Exception, now: datetime, summary: dict) -> None:
    with session_factory() as s:
        event = s.get(WebhookEvent, event_pk, with_for_update=True)
        if event is None:
            return
        event.attempts += 1
        event.last_error = f"{type(exc).__name__}: {exc}"[:500]
        if isinstance(exc, PERMANENT_ERRORS) or event.attempts >= MAX_ATTEMPTS:
            event.status = "DEAD"
            summary["dead"] += 1
        else:
            event.status = "RETRY"
            event.next_attempt_at = now + timedelta(seconds=2 ** event.attempts)
            summary["retried"] += 1
        s.commit()


def internal_payments_view(session: Session) -> list[dict]:
    rows = session.execute(
        select(Payment.reference, Payment.amount, Payment.state, Payment.provider_reference)
    ).all()
    return [{"reference": r.reference, "amount": r.amount, "state": r.state,
             "provider_reference": r.provider_reference} for r in rows]
