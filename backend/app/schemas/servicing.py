"""Request/response schemas for the loan servicing endpoints (utils/servicing.py)."""
from datetime import date
from typing import Annotated

from pydantic import BaseModel, Field, model_validator

Month = Annotated[int, Field(gt=0, le=720)]
Money = Annotated[float, Field(ge=0, le=1e10, allow_inf_nan=False)]


class RateChange(BaseModel):
    month: Month
    annual_rate_percent: float = Field(gt=0, le=100, allow_inf_nan=False)


class ExtraPayment(BaseModel):
    month: Month
    amount: float = Field(gt=0, le=1e10, allow_inf_nan=False)


class PartialPayment(BaseModel):
    month: Month
    amount_paid: Money


class Restructure(BaseModel):
    month: Month
    remaining_months: Month


class ServicingBase(BaseModel):
    """Inputs shared by every servicing endpoint."""
    principal: float = Field(gt=0, le=1e10, allow_inf_nan=False)
    annual_rate_percent: float = Field(gt=0, le=100, allow_inf_nan=False)
    tenure_months: int = Field(gt=0, le=720)
    start_date: date
    holiday_months: list[Month] = Field(default_factory=list, max_length=120)
    rate_changes: list[RateChange] = Field(default_factory=list, max_length=60)
    extra_payments: list[ExtraPayment] = Field(default_factory=list, max_length=240)
    partial_payments: list[PartialPayment] = Field(default_factory=list, max_length=240)
    restructures: list[Restructure] = Field(default_factory=list, max_length=12)
    late_fee: Money = 0
    processing_fee_pct: float = Field(default=0, ge=0, le=10, allow_inf_nan=False)


class ServicingSimulateRequest(ServicingBase):
    pass


class ForeclosureQuoteRequest(ServicingBase):
    month: Month
    foreclosure_charge_pct: float = Field(default=0, ge=0, le=10, allow_inf_nan=False)


class ScenarioSpec(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    holiday_months: list[Month] = Field(default_factory=list, max_length=120)
    rate_changes: list[RateChange] = Field(default_factory=list, max_length=60)
    extra_payments: list[ExtraPayment] = Field(default_factory=list, max_length=240)
    partial_payments: list[PartialPayment] = Field(default_factory=list, max_length=240)
    restructures: list[Restructure] = Field(default_factory=list, max_length=12)


class CompareRequest(ServicingBase):
    """The baseline is always the plain schedule; changes belong in `scenarios`."""
    scenarios: list[ScenarioSpec] = Field(min_length=1, max_length=10)
    horizon_month: Month = 12

    @model_validator(mode="after")
    def no_base_level_changes(self):
        if (self.holiday_months or self.rate_changes or self.extra_payments
                or self.partial_payments or self.restructures):
            raise ValueError("put holidays, rate changes, extras, partials and restructures inside "
                             "scenarios; the baseline is always the plain schedule")
        return self


class ServicingRow(BaseModel):
    month: int
    due_date: date
    kind: str
    opening: str
    interest: str
    fee_charged: str
    installment_paid: str
    principal_paid: str
    extra_paid: str
    closing: str
    event: str


class ServicingSimulateResponse(BaseModel):
    months_taken: int
    maturity_date: date
    principal: str
    total_interest: str
    total_late_fees: str
    processing_fee: str
    total_paid: str
    total_cost: str
    closing_balance: str
    rows: list[ServicingRow]


class ForeclosureQuoteResponse(BaseModel):
    month: int
    outstanding_principal: str
    accrued_interest: str
    foreclosure_charge: str
    total_payable: str


class CompareResponse(BaseModel):
    scenarios: dict[str, dict]
