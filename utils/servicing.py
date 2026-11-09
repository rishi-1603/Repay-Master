"""Decimal-based loan servicing engine.

Covers: rate changes, payment holidays, restructuring, extra (prepayment) payments,
partial payments, late-payment fees, processing fees, foreclosure quotes and
what-if comparisons.

Conventions (all explicit; tested in backend/app/tests/test_servicing*.py):

* Money is `decimal.Decimal`, never float. Amounts are quantized to 0.01, ROUND_HALF_UP.
* Monthly rate = annual percent / 12 / 100 (nominal annual rate, monthly compounding).
* Interest for a month = round(opening balance x monthly rate, 2).
* EMI = annuity payment on the balance over the remaining scheduled months, rounded
  to 0.01. It is recomputed only on a rate change or a restructure.
* Installment allocation: the paid amount covers interest first, then principal.
* Closing balance identity (every row):
      closing = opening + interest + late_fee - installment_paid - extra_paid
* Payment holiday: no installment is due. The month's interest is added to the balance.
  The EMI stays the same and the remaining scheduled months do not shrink, so the loan
  moves out by one month and the extra interest extends the maturity. A holiday month
  cannot also carry a partial or extra payment (raises ValueError).
* Partial payment: the amount paid is less than the installment due. The shortfall
  (interest and principal not paid) stays on the balance and accrues interest. A
  late-payment fee of `late_fee` is charged once for that month and added to the
  balance. Partial payments do not change the EMI, so the loan runs longer.
* Extra payment: applied to principal after that month's installment. The EMI stays
  the same, so the loan ends earlier. Capped at the remaining balance.
* Restructuring at month m: the balance is re-amortised over `remaining_months`
  (counting month m) at the current rate.
* Final installment: if balance + interest is no more than one EMI, the payment is the
  full balance + interest. If one scheduled month remains and the residue is within
  1.00 (EMI rounding), that residue is cleared in that month. Otherwise the EMI is paid
  and the schedule runs until the balance clears, which is how holidays and partial
  payments extend the loan.
* Processing fee: `processing_fee_pct` of principal, reported as an upfront cost. It
  is NOT added to the loan balance.
* Totals: total_paid = principal + total_interest + total_late_fees (proved by the
  closing-balance identity). Total cost = total_interest + total_late_fees + processing_fee.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, getcontext

getcontext().prec = 28
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
MAX_MONTHS = 720
ROUNDING_TOLERANCE = Decimal("1.00")


def q(x) -> Decimal:
    return Decimal(str(x)).quantize(CENT, rounding=ROUND_HALF_UP)


def annuity_emi(balance: Decimal, annual_rate_pct: Decimal, months: int) -> Decimal:
    if months <= 0:
        raise ValueError("months must be positive")
    r = Decimal(str(annual_rate_pct)) / Decimal(1200)
    if r == 0:
        return q(Decimal(str(balance)) / months)
    factor = (1 + r) ** months
    return q(Decimal(str(balance)) * r * factor / (factor - 1))


def add_months(start: date, n: int) -> date:
    """Same day-of-month n months later, clamped to the target month's last day."""
    y, m = divmod(start.month - 1 + n, 12)
    y += start.year
    m += 1
    return date(y, m, min(start.day, calendar.monthrange(y, m)[1]))


def monthly_series(amount, from_month: int, through_month: int, every: int = 1) -> dict[int, Decimal]:
    """Helper for recurring extras: {month: amount} for every `every` months in the range."""
    return {m: q(amount) for m in range(from_month, through_month + 1, every)}


@dataclass
class Row:
    month: int
    due_date: date
    kind: str                  # "PAYMENT" | "HOLIDAY"
    opening: Decimal
    interest: Decimal
    fee_charged: Decimal
    installment_paid: Decimal
    principal_paid: Decimal
    extra_paid: Decimal
    closing: Decimal
    event: str = ""


@dataclass
class Result:
    rows: list[Row] = field(default_factory=list)
    months_taken: int = 0
    principal: Decimal = ZERO
    total_interest: Decimal = ZERO
    total_late_fees: Decimal = ZERO
    processing_fee: Decimal = ZERO
    total_paid: Decimal = ZERO
    closing_balance: Decimal = ZERO
    maturity_date: date | None = None

    @property
    def total_cost(self) -> Decimal:
        return q(self.total_interest + self.total_late_fees + self.processing_fee)

    def balance_after(self, month: int) -> Decimal:
        """Closing balance after `month`. Zero once the loan has closed."""
        if month <= 0:
            return self.principal
        for r in self.rows:
            if r.month == month:
                return r.closing
        return ZERO


def _normalise_map(values, convert) -> dict[int, object]:
    return {int(k): convert(v) for k, v in (values or {}).items()}


def simulate(
    principal,
    annual_rate_pct,
    tenure_months: int,
    start_date: date,
    *,
    rate_changes: dict | None = None,         # month -> new annual rate %
    holidays: set[int] | None = None,         # months with no installment due
    extra_payments: dict | None = None,       # month -> extra principal
    partial_payments: dict | None = None,     # month -> amount actually paid (< installment)
    restructures: dict | None = None,         # month -> remaining months from that month
    late_fee=0,                               # charged per partial-payment month
    processing_fee_pct=0,                     # upfront % of principal
) -> Result:
    balance = q(principal)
    if balance <= 0:
        raise ValueError("principal must be positive")
    rate = Decimal(str(annual_rate_pct))
    if rate < 0:
        raise ValueError("rate must not be negative")
    if not (1 <= tenure_months <= MAX_MONTHS):
        raise ValueError(f"tenure_months must be between 1 and {MAX_MONTHS}")
    late = q(late_fee)
    if late < 0:
        raise ValueError("late_fee must not be negative")
    pct = Decimal(str(processing_fee_pct))
    if pct < 0:
        raise ValueError("processing_fee_pct must not be negative")

    rate_changes = _normalise_map(rate_changes, lambda v: Decimal(str(v)))
    holidays = {int(m) for m in (holidays or set())}
    extra_payments = _normalise_map(extra_payments, q)
    partial_payments = _normalise_map(partial_payments, q)
    restructures = _normalise_map(restructures, int)

    for v in extra_payments.values():
        if v < 0:
            raise ValueError("extra payments must not be negative")
    for v in partial_payments.values():
        if v < 0:
            raise ValueError("partial payments must not be negative")
    clash = sorted(m for m in holidays if m in extra_payments or m in partial_payments)
    if clash:
        raise ValueError(f"month {clash[0]} is a payment holiday and cannot also carry a payment")
    for v in restructures.values():
        if v <= 0:
            raise ValueError("restructure remaining_months must be positive")

    processing_fee = q(Decimal(str(principal)) * pct / 100)
    result = Result(principal=balance, processing_fee=processing_fee)
    remaining = tenure_months
    emi = annuity_emi(balance, rate, remaining)
    month = 0

    while balance > 0:
        month += 1
        if month > MAX_MONTHS:
            raise ValueError("schedule did not close within the supported horizon")
        events: list[str] = []
        if month in rate_changes:
            rate = rate_changes[month]
            events.append(f"rate->{rate}%")
        if month in restructures:
            remaining = restructures[month]
            events.append(f"restructured over {remaining} months")
        if month in rate_changes or month in restructures:
            emi = annuity_emi(balance, rate, max(remaining, 1))

        opening = balance
        interest = q(opening * rate / Decimal(1200))
        due = add_months(start_date, month)

        if month in holidays:
            balance = q(opening + interest)
            events.append("payment holiday")
            result.rows.append(Row(month, due, "HOLIDAY", opening, interest, ZERO,
                                   ZERO, ZERO, ZERO, balance, "; ".join(events)))
            result.total_interest += interest
            continue

        due_amount = q(opening + interest)
        scheduled = due_amount if (due_amount <= emi or (
            remaining <= 1 and due_amount - emi <= ROUNDING_TOLERANCE)) else emi
        if scheduled == due_amount:
            events.append("final installment")

        paid = scheduled
        if month in partial_payments:
            paid = min(partial_payments[month], scheduled)
            events.append(f"partial payment {paid} of {scheduled}")
        fee = ZERO
        if paid < scheduled:
            fee = late
            if fee:
                events.append(f"late fee {fee}")

        interest_part = min(paid, interest)
        principal_part = q(paid - interest_part)
        balance = q(opening + interest + fee - paid)

        extra = ZERO
        if month in extra_payments and balance > 0:
            extra = min(extra_payments[month], balance)
            balance = q(balance - extra)
            if extra:
                events.append(f"extra {extra}")

        result.rows.append(Row(month, due, "PAYMENT", opening, interest, fee, paid,
                               principal_part, extra, balance, "; ".join(events)))
        result.total_interest += interest
        result.total_late_fees += fee
        result.total_paid += paid + extra
        remaining = max(remaining - 1, 0)

    result.months_taken = month
    result.total_interest = q(result.total_interest)
    result.total_late_fees = q(result.total_late_fees)
    result.total_paid = q(result.total_paid)
    result.closing_balance = balance
    result.maturity_date = result.rows[-1].due_date
    return result


def foreclosure_quote(principal, annual_rate_pct, tenure_months, start_date, month: int,
                      foreclosure_charge_pct=0, **scenario) -> dict:
    """Amount needed to close the loan before installment `month` is paid.

    Outstanding = balance after month-1, plus interest accrued for `month` at the rate
    in effect at that month, plus a foreclosure charge on the outstanding principal.
    """
    if month < 1:
        raise ValueError("month must be at least 1")
    res = simulate(principal, annual_rate_pct, tenure_months, start_date, **scenario)
    if month > res.months_taken:
        raise ValueError(f"loan already closed in month {res.months_taken}")
    outstanding = res.balance_after(month - 1)
    rate = Decimal(str(annual_rate_pct))
    for m in sorted(scenario.get("rate_changes") or {}):
        if m <= month:
            rate = Decimal(str(scenario["rate_changes"][m]))
    accrued = q(outstanding * rate / Decimal(1200))
    charge = q(outstanding * Decimal(str(foreclosure_charge_pct)) / 100)
    return {
        "month": month,
        "outstanding_principal": str(outstanding),
        "accrued_interest": str(accrued),
        "foreclosure_charge": str(charge),
        "total_payable": str(q(outstanding + accrued + charge)),
    }


def compare_scenarios(principal, annual_rate_pct, tenure_months, start_date,
                      scenarios: dict[str, dict], horizon_month: int = 12) -> dict:
    """Run a baseline plus named scenarios and compare the outcomes."""
    base = simulate(principal, annual_rate_pct, tenure_months, start_date)
    out = {"baseline": _summary(base, base, horizon_month)}
    for name, kwargs in scenarios.items():
        res = simulate(principal, annual_rate_pct, tenure_months, start_date, **kwargs)
        out[name] = _summary(res, base, horizon_month)
    return out


def _summary(res: Result, base: Result, horizon_month: int) -> dict:
    return {
        "months_taken": res.months_taken,
        "maturity_date": res.maturity_date.isoformat(),
        "total_interest": str(res.total_interest),
        "total_late_fees": str(res.total_late_fees),
        "total_paid": str(res.total_paid),
        "total_cost": str(res.total_cost),
        "months_saved_vs_baseline": base.months_taken - res.months_taken,
        "interest_saved_vs_baseline": str(q(base.total_interest - res.total_interest)),
        "balance_at_horizon": str(res.balance_after(horizon_month)),
    }
