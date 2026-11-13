"""Loan ledger endpoints: create loans, post repayments, reverse them, statements and arrears.

Every endpoint is owner-scoped. A user can only see and change their own loans, and
a loan belonging to someone else returns 404 rather than 403, so loan ids cannot be probed.
"""
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import get_current_username
from app.db.base import get_db
from app.db.models import LoanAccount
from app.schemas.ledger import DueDateUpdate, JournalEntryView, LoanCreate, LoanView, RepaymentCreate
from app.services import delinquency, ledger, statements
from app.services.ledger import LedgerError

router = APIRouter(prefix="/ledger", tags=["ledger"])


def _raise(exc: LedgerError) -> None:
    raise HTTPException(status_code=exc.status, detail=str(exc))


def _loan_view(loan: LoanAccount, as_of: date) -> LoanView:
    return LoanView(
        id=loan.id,
        opening_balance=f"{loan.opening_balance:.2f}",
        balance=f"{loan.balance:.2f}",
        due_date=loan.due_date,
        days_past_due=delinquency.days_past_due(loan.due_date, as_of) if loan.balance > 0 else 0,
        delinquency_bucket=delinquency.bucket_for(loan.balance, loan.due_date, as_of),
    )


def _entry_view(entry) -> JournalEntryView:
    return JournalEntryView(
        id=entry.id, loan_id=entry.loan_id, posted_on=entry.posted_on, kind=entry.kind,
        amount=f"{entry.amount:.2f}", reverses_id=entry.reverses_id,
    )


@router.post("/loans", response_model=LoanView, status_code=201)
def create_loan(payload: LoanCreate, username: str = Depends(get_current_username),
                db: Session = Depends(get_db)) -> LoanView:
    try:
        loan = ledger.create_loan(db, username, payload.principal, payload.due_date,
                                  payload.opened_on or date.today())
    except LedgerError as exc:
        _raise(exc)
    return _loan_view(loan, date.today())


@router.get("/loans/{loan_id}", response_model=LoanView)
def get_loan(loan_id: int, username: str = Depends(get_current_username),
             db: Session = Depends(get_db)) -> LoanView:
    try:
        loan = ledger.get_loan(db, username, loan_id)
    except LedgerError as exc:
        _raise(exc)
    return _loan_view(loan, date.today())


@router.post("/loans/{loan_id}/repayments", response_model=JournalEntryView, status_code=201)
def post_repayment(loan_id: int, payload: RepaymentCreate, username: str = Depends(get_current_username),
                   db: Session = Depends(get_db)) -> JournalEntryView:
    try:
        entry = ledger.post_repayment(db, username, loan_id, payload.amount, payload.posted_on or date.today())
    except LedgerError as exc:
        _raise(exc)
    return _entry_view(entry)


@router.post("/repayments/{entry_id}/reverse", response_model=JournalEntryView, status_code=201)
def reverse_repayment(entry_id: int, username: str = Depends(get_current_username),
                      db: Session = Depends(get_db)) -> JournalEntryView:
    try:
        entry = ledger.reverse_repayment(db, username, entry_id, date.today())
    except LedgerError as exc:
        _raise(exc)
    return _entry_view(entry)


@router.put("/loans/{loan_id}/due-date", response_model=LoanView)
def set_due_date(loan_id: int, payload: DueDateUpdate, username: str = Depends(get_current_username),
                 db: Session = Depends(get_db)) -> LoanView:
    try:
        loan = ledger.set_due_date(db, username, loan_id, payload.due_date)
    except LedgerError as exc:
        _raise(exc)
    return _loan_view(loan, date.today())


@router.get("/loans/{loan_id}/statement")
def loan_statement(loan_id: int, start: date | None = Query(None, alias="from"),
                   end: date | None = Query(None, alias="to"),
                   username: str = Depends(get_current_username), db: Session = Depends(get_db)) -> dict:
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="'from' must not be after 'to'")
    try:
        loan = ledger.get_loan(db, username, loan_id)
    except LedgerError as exc:
        _raise(exc)
    return statements.build_statement(loan, ledger.entries_for(db, loan.id), start, end)


@router.get("/delinquency")
def delinquency_report(as_of: date | None = None, username: str = Depends(get_current_username),
                       db: Session = Depends(get_db)) -> dict:
    as_of = as_of or date.today()
    loans = db.execute(select(LoanAccount).where(LoanAccount.owner == username).order_by(LoanAccount.id)).scalars()
    totals = {bucket: {"count": 0, "_sum": Decimal("0.00")} for bucket in delinquency.BUCKETS}
    rows = []
    for loan in loans:
        bucket = delinquency.bucket_for(loan.balance, loan.due_date, as_of)
        totals[bucket]["count"] += 1
        totals[bucket]["_sum"] += loan.balance
        if bucket in delinquency.ARREARS_BUCKETS:
            rows.append({"loan_id": loan.id, "balance": f"{loan.balance:.2f}",
                         "due_date": loan.due_date.isoformat(),
                         "days_past_due": delinquency.days_past_due(loan.due_date, as_of),
                         "bucket": bucket})
    summary = {
        bucket: {"count": t["count"], "balance": f"{t['_sum']:.2f}"} for bucket, t in totals.items()
    }
    return {"as_of": as_of.isoformat(), "buckets": summary, "overdue_loans": rows}
