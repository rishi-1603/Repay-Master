"""Posting rules for loans: repayments, reversals and due dates.

Every change runs in one transaction that locks the loan row first
(SELECT ... FOR UPDATE), so two concurrent repayments on the same loan cannot
both pass the balance check. The journal row and the cached balance change
together or not at all.
"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import JournalEntry, LoanAccount

CENT = Decimal("0.01")


class LedgerError(Exception):
    """Base class for domain rule violations. `status` is the HTTP status to return."""

    status = 422


class NotFound(LedgerError):
    status = 404


class Conflict(LedgerError):
    status = 409


def quantize(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _require_positive(amount: Decimal, label: str) -> Decimal:
    amount = quantize(amount)
    if amount <= 0:
        raise LedgerError(f"{label} must be greater than zero")
    return amount


def _lock_loan(db: Session, owner: str, loan_id: int) -> LoanAccount:
    loan = db.execute(
        select(LoanAccount)
        .where(LoanAccount.id == loan_id, LoanAccount.owner == owner)
        .with_for_update()
    ).scalar_one_or_none()
    if loan is None:
        raise NotFound("loan not found")
    return loan


def create_loan(db: Session, owner: str, principal: Decimal, due_date: date | None, opened_on: date) -> LoanAccount:
    principal = _require_positive(principal, "principal")
    loan = LoanAccount(
        owner=owner, opening_balance=principal, balance=principal, due_date=due_date, opened_on=opened_on
    )
    db.add(loan)
    db.commit()
    db.refresh(loan)
    return loan


def get_loan(db: Session, owner: str, loan_id: int) -> LoanAccount:
    loan = db.execute(
        select(LoanAccount).where(LoanAccount.id == loan_id, LoanAccount.owner == owner)
    ).scalar_one_or_none()
    if loan is None:
        raise NotFound("loan not found")
    return loan


def post_repayment(db: Session, owner: str, loan_id: int, amount: Decimal, posted_on: date) -> JournalEntry:
    amount = _require_positive(amount, "amount")
    try:
        loan = _lock_loan(db, owner, loan_id)
        if amount > loan.balance:
            raise Conflict(f"amount exceeds the outstanding balance of {loan.balance}")
        loan.balance = quantize(loan.balance - amount)
        entry = JournalEntry(loan_id=loan.id, posted_on=posted_on, kind="repayment", amount=amount)
        db.add(entry)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(entry)
    return entry


def reverse_repayment(db: Session, owner: str, entry_id: int, posted_on: date) -> JournalEntry:
    try:
        original = db.execute(
            select(JournalEntry).join(LoanAccount).where(
                JournalEntry.id == entry_id, LoanAccount.owner == owner
            )
        ).scalar_one_or_none()
        if original is None:
            raise NotFound("repayment not found")
        if original.kind != "repayment":
            raise Conflict("only a repayment can be reversed")
        loan = _lock_loan(db, owner, original.loan_id)
        already = db.execute(
            select(JournalEntry.id).where(JournalEntry.reverses_id == original.id)
        ).scalar_one_or_none()
        if already is not None:
            raise Conflict("this repayment has already been reversed")
        loan.balance = quantize(loan.balance + original.amount)
        entry = JournalEntry(
            loan_id=loan.id, posted_on=posted_on, kind="reversal", amount=original.amount, reverses_id=original.id
        )
        db.add(entry)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(entry)
    return entry


def set_due_date(db: Session, owner: str, loan_id: int, due_date: date | None) -> LoanAccount:
    try:
        loan = _lock_loan(db, owner, loan_id)
        loan.due_date = due_date
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(loan)
    return loan


def entries_for(db: Session, loan_id: int) -> list[JournalEntry]:
    return list(
        db.execute(
            select(JournalEntry).where(JournalEntry.loan_id == loan_id).order_by(JournalEntry.posted_on, JournalEntry.id)
        ).scalars()
    )
