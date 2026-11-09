"""Request/response schemas for loans, payments, webhooks and reconciliation."""
from pydantic import BaseModel, Field


class LoanCreate(BaseModel):
    loan_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    principal_outstanding: float = Field(ge=0, le=1e10, allow_inf_nan=False)
    interest_due: float = Field(default=0, ge=0, le=1e10, allow_inf_nan=False)
    fees_due: float = Field(default=0, ge=0, le=1e10, allow_inf_nan=False)


class PaymentCreate(BaseModel):
    amount: float = Field(gt=0, le=1e10, allow_inf_nan=False)
    idempotency_key: str = Field(min_length=8, max_length=128)


class ReconRow(BaseModel):
    reference: str = Field(min_length=1, max_length=64)
    amount: float = Field(ge=0, le=1e10, allow_inf_nan=False)
    status: str = Field(pattern=r"^(settled|refunded)$")


class ReconRequest(BaseModel):
    settlement: list[ReconRow] = Field(max_length=10000)
