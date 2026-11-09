"""Reconciliation reports (persisted) and ledger integrity checks.

Integrity checks answer: do the books agree with the payments and loans they describe?
  * every journal entry balances, and the whole ledger's trial balance is zero;
  * every payment's journal entries match its status (none for pending/failed,
    one success entry for successful, plus a reversal that nets the original to zero);
  * for each successful payment, the amount posted to each account equals what the payment
    applied: clearing = amount, principal, interest, fee and overpayment credit;
  * each loan's principal, interest and fees reconcile: original - applied == current balance.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import JournalEntry, LoanAccount, Payment, ReconciliationException, ReconciliationRun
from app.domain.ledger import DEBIT, trial_balance_is_zero
from app.domain.reconciliation import reconcile
from app.services import ledger_service
from app.services.payments import internal_payments_view


def persist_reconciliation(session: Session, run_by: str, settlement: list[dict]) -> ReconciliationRun:
    internal = internal_payments_view(session)
    exceptions = reconcile(internal, settlement)
    run = ReconciliationRun(run_by=run_by, checked_internal=len(internal),
                            checked_settlement=len(settlement), exception_count=len(exceptions))
    run.exceptions = [ReconciliationException(kind=e["type"], reference=e["reference"], detail=e["detail"])
                      for e in exceptions]
    session.add(run)
    session.commit()
    return run


def run_view(run: ReconciliationRun) -> dict:
    return {
        "run_id": run.id,
        "run_by": run.run_by,
        "checked_internal": run.checked_internal,
        "checked_settlement": run.checked_settlement,
        "exception_count": run.exception_count,
        "exceptions": [{"type": e.kind, "reference": e.reference, "detail": e.detail}
                       for e in run.exceptions],
    }


def _net_by_account(entries: list[JournalEntry]) -> dict[str, int]:
    """Debits minus credits per account, summed over the given entries."""
    net: dict[str, int] = {}
    for entry in entries:
        for ln in entry.lines:
            net[ln.account] = net.get(ln.account, 0) + (ln.amount if ln.side == DEBIT else -ln.amount)
    return {acct: amount for acct, amount in net.items() if amount != 0}


def _entry_is_balanced(entry: JournalEntry) -> bool:
    return sum(ln.amount if ln.side == DEBIT else -ln.amount for ln in entry.lines) == 0


def _applied_sum(payments: list[Payment], loan_id: str, column: str) -> int:
    return sum(getattr(p, column) for p in payments if p.loan_id == loan_id and p.state == "SUCCESSFUL")


def ledger_integrity(session: Session) -> list[dict]:
    issues: list[dict] = []
    lines = ledger_service.all_lines(session)
    if not trial_balance_is_zero(lines):
        issues.append({"type": "TRIAL_BALANCE_NOT_ZERO", "reference": "ledger",
                       "detail": "total debits differ from total credits"})

    entries_all = session.scalars(select(JournalEntry)).all()
    for entry in entries_all:
        if not _entry_is_balanced(entry):
            issues.append({"type": "ENTRY_UNBALANCED", "reference": entry.idempotency_key,
                           "detail": "debits differ from credits within this entry"})
    entries = {e.idempotency_key: e for e in entries_all}
    payments = session.scalars(select(Payment)).all()

    for p in payments:
        success = entries.get(f"payment:{p.id}:success")
        reversal = entries.get(f"payment:{p.id}:reversal")
        applied_total = p.fee_applied + p.interest_applied + p.principal_applied + p.credit_applied
        if p.state in ("INITIATED", "PENDING", "FAILED"):
            if success is not None:
                issues.append({"type": "POSTED_BUT_NOT_SUCCESSFUL", "reference": p.reference,
                               "detail": f"state {p.state} has a success entry"})
            if applied_total != 0:
                issues.append({"type": "APPLIED_WITHOUT_SUCCESS", "reference": p.reference,
                               "detail": f"state {p.state} records {applied_total} as applied"})
            continue
        if success is None:
            issues.append({"type": "SUCCESSFUL_WITHOUT_ENTRY", "reference": p.reference,
                           "detail": f"state {p.state} has no success entry"})
            continue

        if applied_total != p.amount:
            issues.append({"type": "AMOUNT_NOT_ALLOCATED", "reference": p.reference,
                           "detail": f"applied {applied_total} for a payment of {p.amount}"})
        expected = {"payment_clearing": p.amount,
                    "loan_receivable": -p.principal_applied,
                    "interest_income": -p.interest_applied,
                    "fee_income": -p.fee_applied,
                    "customer_credit": -p.credit_applied}
        expected = {acct: amt for acct, amt in expected.items() if amt != 0}
        actual = _net_by_account([success])
        if actual != expected:
            issues.append({"type": "ALLOCATION_MISMATCH", "reference": p.reference,
                           "detail": f"posted {actual} but the payment applied {expected}"})

        if p.state == "REVERSED":
            if reversal is None:
                issues.append({"type": "REVERSAL_NOT_POSTED", "reference": p.reference,
                               "detail": "state REVERSED without a reversal entry"})
            elif _net_by_account([success, reversal]) != {}:
                issues.append({"type": "REVERSAL_NOT_NETTED", "reference": p.reference,
                               "detail": "original and reversal do not net to zero"})
        if p.state == "SUCCESSFUL" and reversal is not None:
            issues.append({"type": "REVERSAL_POSTED_BUT_SUCCESSFUL", "reference": p.reference,
                           "detail": "reversal entry exists while state is SUCCESSFUL"})

    for loan in session.scalars(select(LoanAccount)).all():
        checks = (
            ("principal", loan.principal_original, "principal_applied", loan.principal_outstanding),
            ("interest", loan.interest_original, "interest_applied", loan.interest_due),
            ("fees", loan.fees_original, "fee_applied", loan.fees_due),
        )
        for component, original, column, current in checks:
            applied = _applied_sum(payments, loan.id, column)
            if original - applied != current:
                issues.append({"type": "LOAN_BALANCE_MISMATCH", "reference": loan.id,
                               "detail": f"{component}: original {original} - applied {applied} "
                                         f"!= balance {current}"})
    return issues
