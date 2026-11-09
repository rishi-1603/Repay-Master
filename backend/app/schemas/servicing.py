"""Request/response schemas for the loan servicing simulator."""
from datetime import date
from typing import Annotated

from pydantic import BaseModel, Field

Month = Annotated[int, Field(gt=0, le=720)]


class RateChange(BaseModel):
    month: int = Field(gt=0, le=720)
    annual_rate_percent: float = Field(gt=0, le=100, allow_inf_nan=False)


class ExtraPayment(BaseModel):
    month: int = Field(gt=0, le=720)
    amount: float = Field(gt=0, allow_inf_nan=False)


class Restructure(BaseModel):
    month: int = Field(gt=0, le=720)
    remaining_months: int = Field(gt=0, le=720)


class ServicingSimulateRequest(BaseModel):
    principal: float = Field(gt=0, le=1e10, allow_inf_nan=False)
    annual_rate_percent: float = Field(gt=0, le=100, allow_inf_nan=False)
    tenure_months: int = Field(gt=0, le=720)
    start_date: date
    holiday_months: list[Month] = Field(default_factory=list, max_length=120)
    rate_changes: list[RateChange] = Field(default_factory=list, max_length=60)
    extra_payments: list[ExtraPayment] = Field(default_factory=list, max_length=240)
    restructures: list[Restructure] = Field(default_factory=list, max_length=12)


class ServicingRow(BaseModel):
    month: int
    due_date: date
    kind: str
    opening: str
    interest: str
    installment_paid: str
    principal_paid: str
    extra_paid: str
    capitalised: str
    closing: str
    event: str


class ServicingSimulateResponse(BaseModel):
    months_taken: int
    total_interest: str
    total_paid: str
    closing_balance: str
    rows: list[ServicingRow]
