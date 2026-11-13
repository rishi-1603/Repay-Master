"""Request and response models for loans, repayments and statements."""
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class LoanCreate(BaseModel):
    principal: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    due_date: date | None = None
    opened_on: date | None = None


class DueDateUpdate(BaseModel):
    due_date: date | None


class RepaymentCreate(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    posted_on: date | None = None


class LoanView(BaseModel):
    id: int
    opening_balance: str
    balance: str
    due_date: date | None
    days_past_due: int
    delinquency_bucket: str


class JournalEntryView(BaseModel):
    id: int
    loan_id: int
    posted_on: date
    kind: str
    amount: str
    reverses_id: int | None
