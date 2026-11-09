"""Payment intents, webhook processing and reconciliation.

Every state change and its journal entry commit in ONE transaction. Idempotency is
enforced in three places, in order:
  1. webhook_events.event_id unique: a redelivered webhook is recognised and skipped.
  2. payments(loan_id, idempotency_key) unique: a retried intent returns the same payment.
  3. journal_entries.idempotency_key unique: a payment's money moves at most once.
Row locks (SELECT ... FOR UPDATE) serialise concurrent webhooks for the same payment on
PostgreSQL. SQLite serialises writers itself.
"""
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import JournalEntry, LoanAccount, Payment, WebhookEvent
from app.domain.ledger import Line, repayment_lines, reversal_lines
from app.domain.payments import InvalidTransition, Overpayment, PaymentState, allocate, transition
from app.services.ledger_service import post_entry


class IdempotencyConflict(ValueError):
    pass


class NotFound(LookupError):
    pass


def get_owned_loan(session: Session, loan_id: str, owner: str) -> LoanAccount:
    loan = session.get(LoanAccount, loan_id)
    if loan is None or loan.owner != owner:
        raise NotFound(f"loan {loan_id} not found")   # same answer whether it exists or not
    return loan


def amount_owed(loan: LoanAccount) -> int:
    return loan.fees_due + loan.interest_due + loan.principal_outstanding


def create_intent(session: Session, loan: LoanAccount, amount: int, idempotency_key: str) -> tuple[Payment, bool]:
    """Create a payment intent. Returns (payment, created). A replay with the same key and
    amount returns the original payment; the same key with a different amount is a conflict."""
    existing = session.scalar(select(Payment).where(
        Payment.loan_id == loan.id, Payment.idempotency_key == idempotency_key))
    if existing is not None:
        if existing.amount != amount:
            raise IdempotencyConflict("idempotency key was already used for a different amount")
        return existing, False
    if amount > amount_owed(loan):
        raise Overpayment("payment exceeds the amount owed")
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


def _post_suspense(session: Session, key: str, amount: int, description: str) -> None:
    post_entry(session, key, description, [Line("payment_clearing", "D", amount),
                                           Line("suspense", "C", amount)])


def _apply_success(session: Session, payment: Payment, provider_reference: str | None) -> str:
    loan = session.get(LoanAccount, payment.loan_id, with_for_update=True)
    try:
        transition(PaymentState(payment.state), PaymentState.SUCCESSFUL)
        fee, interest, principal = allocate(payment.amount, loan.fees_due, loan.interest_due,
                                            loan.principal_outstanding)
    except (InvalidTransition, Overpayment) as exc:
        # Money has arrived but cannot be applied cleanly. Park it in suspense for a human.
        _post_suspense(session, f"payment:{payment.id}:suspense", payment.amount,
                       f"unapplied receipt {payment.reference}: {exc}")
        return "needs_review"
    payment.state = PaymentState.SUCCESSFUL.value
    payment.provider_reference = provider_reference or payment.provider_reference
    payment.fee_applied, payment.interest_applied, payment.principal_applied = fee, interest, principal
    loan.fees_due -= fee
    loan.interest_due -= interest
    loan.principal_outstanding -= principal
    post_entry(session, f"payment:{payment.id}:success", f"repayment {payment.reference}",
               repayment_lines(payment.amount, principal, interest, fee))
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


HANDLERS = {
    "payment.succeeded": "success",
    "payment.failed": "failed",
    "payment.reversed": "reversed",
}


def process_webhook(session: Session, event_id: str, event_type: str, data: dict, raw_body: bytes) -> str:
    """Process one verified webhook. Returns a result string; never double-applies."""
    session.add(WebhookEvent(event_id=event_id, event_type=event_type,
                             payload=raw_body.decode("utf-8", "replace"), result="received",
                             received_at=datetime.now(timezone.utc)))
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        return "duplicate"

    action = HANDLERS.get(event_type)
    if action is None:
        result = "ignored"
    else:
        payment = session.scalar(select(Payment).where(Payment.reference == data.get("reference")
                                                       ).with_for_update())
        if payment is None:
            result = "unknown_payment"
            _record(session, event_id, result)
            session.commit()
            return result
        if action == "success":
            if payment.state == PaymentState.SUCCESSFUL.value:
                result = "already_applied"
            else:
                result = _apply_success(session, payment, data.get("provider_reference"))
        elif action == "failed":
            result = "already_applied" if payment.state == PaymentState.FAILED.value else _apply_failure(session, payment)
        else:
            result = _apply_reversal(session, payment)

    _record(session, event_id, result)
    session.commit()
    return result


def _record(session: Session, event_id: str, result: str) -> None:
    row = session.scalar(select(WebhookEvent).where(WebhookEvent.event_id == event_id))
    row.result = result


def internal_payments_view(session: Session) -> list[dict]:
    rows = session.execute(
        select(Payment.reference, Payment.amount, Payment.state, Payment.provider_reference)
    ).all()
    return [{"reference": r.reference, "amount": r.amount, "state": r.state,
             "provider_reference": r.provider_reference} for r in rows]

