"""Decimal-based loan servicing engine: rate changes, payment holidays, restructuring,
extra payments.

Conventions (all explicit, all tested in backend/app/tests/test_servicing.py):

* Money is `decimal.Decimal`, never float. Every monetary amount is quantized to
  0.01 with ROUND_HALF_UP.
* Monthly rate = annual percent / 12 / 100 (nominal annual rate, monthly compounding).
* Interest for a month = round(opening balance x monthly rate, 2).
* EMI = annuity payment on the balance over the remaining scheduled months,
  rounded to 0.01. It is recomputed only when the rate changes or the loan is
  restructured.
* Payment holiday: the installment is not paid, and that month's interest is
  capitalised (added to principal). The EMI is NOT recomputed and the remaining
  scheduled months are NOT reduced, so the schedule moves out by one month. The
  capitalised interest extends the maturity; no balloon payment is created.
* Extra payment: applied to principal after that month's installment. The EMI is
  kept unchanged, so the loan ends earlier.
* Restructuring at month m: the balance is re-amortised over `remaining_months`
  months (counting month m) at the current rate.
* Final installment: if balance + interest is no more than one EMI, the payment is
  balance + interest, so the closing balance is 0.00. When one scheduled month
  remains and the residue is within 1.00 (EMI rounding), the residue is cleared in
  that month. Otherwise the EMI is paid and the schedule runs on until the balance is
  cleared, which is how holidays extend the loan.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, getcontext

getcontext().prec = 28
CENT = Decimal("0.01")
MAX_MONTHS = 720
ROUNDING_TOLERANCE = Decimal("1.00")


def q(x) -> Decimal:
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


def annuity_emi(balance: Decimal, annual_rate_pct: Decimal, months: int) -> Decimal:
    if months <= 0:
        raise ValueError("months must be positive")
    r = annual_rate_pct / Decimal(1200)
    if r == 0:
        return q(balance / months)
    factor = (1 + r) ** months
    return q(balance * r * factor / (factor - 1))


def add_months(start: date, n: int) -> date:
    """Return the same day-of-month n months later, clamped to the month's last day."""
    import calendar
    y, m = divmod(start.month - 1 + n, 12)
    y += start.year
    m += 1
    day = min(start.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


@dataclass
class Row:
    month: int
    due_date: date
    kind: str            # "PAYMENT" | "HOLIDAY"
    opening: Decimal
    interest: Decimal
    installment_paid: Decimal
    principal_paid: Decimal
    extra_paid: Decimal
    capitalised: Decimal
    closing: Decimal
    event: str = ""


@dataclass
class Result:
    rows: list[Row] = field(default_factory=list)
    months_taken: int = 0
    total_interest: Decimal = Decimal("0.00")
    total_paid: Decimal = Decimal("0.00")
    closing_balance: Decimal = Decimal("0.00")

    def balance_after(self, month: int) -> Decimal:
        for r in self.rows:
            if r.month == month:
                return r.closing
        raise KeyError(month)


def simulate(
    principal,
    annual_rate_pct,
    tenure_months: int,
    start_date: date,
    *,
    rate_changes: dict[int, object] | None = None,     # month -> new annual rate %
    holidays: set[int] | None = None,                   # months with no installment
    extra_payments: dict[int, object] | None = None,    # month -> extra principal
    restructures: dict[int, int] | None = None,         # month -> remaining months from that month
) -> Result:
    balance = q(principal)
    if balance <= 0:
        raise ValueError("principal must be positive")
    rate = Decimal(str(annual_rate_pct))
    if rate < 0:
        raise ValueError("rate must not be negative")
    if not (1 <= tenure_months <= MAX_MONTHS):
        raise ValueError(f"tenure_months must be between 1 and {MAX_MONTHS}")

    rate_changes = {int(k): Decimal(str(v)) for k, v in (rate_changes or {}).items()}
    holidays = {int(m) for m in (holidays or set())}
    extra_payments = {int(k): q(v) for k, v in (extra_payments or {}).items()}
    restructures = {int(k): int(v) for k, v in (restructures or {}).items()}

    for m, v in restructures.items():
        if v <= 0:
            raise ValueError("restructure remaining_months must be positive")

    remaining = tenure_months
    emi = annuity_emi(balance, rate, remaining)
    result = Result()
    month = 0

    while balance > 0:
        month += 1
        if month > MAX_MONTHS:
            raise ValueError("schedule did not close within the supported horizon")
        events = []
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
            balance = q(balance + interest)
            events.append("payment holiday")
            result.rows.append(Row(month, due, "HOLIDAY", opening, interest, Decimal("0.00"),
                                   Decimal("0.00"), Decimal("0.00"), interest, balance,
                                   "; ".join(events)))
            result.total_interest += interest
            continue

        due_amount = opening + interest
        if due_amount <= emi or (remaining <= 1 and due_amount - emi <= ROUNDING_TOLERANCE):
            payment = due_amount
            events.append("final installment")
        else:
            payment = emi
        principal_part = q(payment - interest)
        balance = q(opening - principal_part)

        extra = Decimal("0.00")
        if month in extra_payments and balance > 0:
            extra = min(extra_payments[month], balance)
            balance = q(balance - extra)
            events.append(f"extra {extra}")

        result.rows.append(Row(month, due, "PAYMENT", opening, interest, payment, principal_part,
                               extra, Decimal("0.00"), balance, "; ".join(events)))
        result.total_interest += interest
        result.total_paid += payment + extra
        remaining = max(remaining - 1, 0)

    result.months_taken = month
    result.total_interest = q(result.total_interest)
    result.total_paid = q(result.total_paid)
    result.closing_balance = balance
    return result
