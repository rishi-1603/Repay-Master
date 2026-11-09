"""Reconciliation reports (persisted) and ledger integrity checks.

Integrity checks answer: do the books agree with the payments and loans they describe?
  * the whole ledger balances (trial balance is zero);
  * every payment's journal entries match its status (none for pending/failed,
    one success entry for successful, plus a reversal for reversed);
  * the amounts posted for each payment equal the amount applied to the loan;
  * each loan's principal reconciles: original - applied payments == outstanding.
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


def ledger_integrity(session: Session) -> list[dict]:
    issues: list[dict] = []
    lines = ledger_service.all_lines(session)
    if not trial_balance_is_zero(lines):
        issues.append({"type": "TRIAL_BALANCE_NOT_ZERO", "reference": "ledger",
                       "detail": "total debits differ from total credits"})

    entries = {e.idempotency_key: e for e in session.scalars(select(JournalEntry)).all()}
    payments = session.scalars(select(Payment)).all()
    for p in payments:
        success = entries.get(f"payment:{p.id}:success")
        reversal = entries.get(f"payment:{p.id}:reversal")
        if p.state in ("INITIATED", "PENDING", "FAILED"):
            if success is not None:
                issues.append({"type": "POSTED_BUT_NOT_SUCCESSFUL", "reference": p.reference,
                               "detail": f"state {p.state} has a success entry"})
            continue
        if success is None:
            issues.append({"type": "SUCCESSFUL_WITHOUT_ENTRY", "reference": p.reference,
                           "detail": f"state {p.state} has no success entry"})
            continue
        clearing = sum(ln.amount for ln in success.lines if ln.account == "payment_clearing" and ln.side == DEBIT)
        if clearing != p.amount:
            issues.append({"type": "AMOUNT_NOT_POSTED", "reference": p.reference,
                           "detail": f"posted {clearing} for a payment of {p.amount}"})
        receivable = sum(ln.amount for ln in success.lines if ln.account == "loan_receivable")
        if receivable != p.principal_applied:
            issues.append({"type": "ALLOCATION_MISMATCH", "reference": p.reference,
                           "detail": "posted principal differs from the applied principal"})
        if p.state == "REVERSED" and reversal is None:
            issues.append({"type": "REVERSAL_NOT_POSTED", "reference": p.reference,
                           "detail": "state REVERSED without a reversal entry"})
        if p.state == "SUCCESSFUL" and reversal is not None:
            issues.append({"type": "REVERSAL_POSTED_BUT_SUCCESSFUL", "reference": p.reference,
                           "detail": "reversal entry exists while state is SUCCESSFUL"})

    for loan in session.scalars(select(LoanAccount)).all():
        applied = sum(p.principal_applied for p in payments if p.loan_id == loan.id and p.state == "SUCCESSFUL")
        if loan.principal_original - applied != loan.principal_outstanding:
            issues.append({"type": "LOAN_BALANCE_MISMATCH", "reference": loan.id,
                           "detail": f"original {loan.principal_original} - applied {applied} "
                                     f"!= outstanding {loan.principal_outstanding}"})
    return issues
