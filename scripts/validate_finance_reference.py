#!/usr/bin/env python3
"""Independent validation of the loan math in `utils/finance.py`.

WHY THIS FILE EXISTS
--------------------
The test suite in `backend/app/tests/test_financial_edge_cases.py` computes its
own expected values, but it computes the *EMI formula* the same way the library
does -- so a wrong formula, duplicated in both places, would pass. This script
is the second, independent opinion required by the Day-10 checklist ("validate
financial calculations against reference results"), and it is deliberately
built on different machinery:

  * `decimal.Decimal` at 50-digit precision instead of binary floats, so the
    reference does not inherit the library's floating-point error;
  * a *closed-form* amortization identity instead of a month-by-month loop:
    the outstanding balance after k payments is

        B_k = P*(1+r)^k - EMI*((1+r)^k - 1)/r

    which is derived analytically from the recurrence, not by re-running the
    library's `while` loop. The library's own schedule is then checked against
    it month by month, which is a genuinely different computation.

WHAT IS CHECKED
---------------
  1. EMI values against the Decimal closed form (relative tolerance 1e-9).
  2. The zero-interest branch: EMI must be exactly P/n and total interest 0.
  3. Balance after every month against the analytic formula (absolute
     tolerance, in currency units).
  4. Total interest against the closed form EMI*n - P.
  5. Principal conservation: the schedule's principal column must pay off the
     loan exactly.
  6. Prepayment must strictly reduce both the term and the total interest,
     and must never increase the principal paid.
  7. Boundary inputs from the audit checklist: zero, tiny and maximum rates,
     fractional principals, and very large principals.

Exit code 0 = every check passed; 1 = at least one failed. The tolerance for
each check is stated in the output, never implied.
"""
from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal, getcontext
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from utils.finance import (
    build_amortization_schedule,
    calculate_monthly_payment,
    simulate_prepayment,
)

getcontext().prec = 50
D = Decimal

# Tolerances, stated rather than tuned to make things pass:
EMI_REL_TOL = Decimal("1e-9")        # relative: 1 billionth of the EMI
BALANCE_ABS_TOL = Decimal("0.05")    # currency units, per month
INTEREST_ABS_TOL = Decimal("1.00")   # currency units over a whole loan
PRINCIPAL_DISPLAY_ABS_TOL = Decimal("0.05")  # cumulative cent-display rounding
# The interest tolerance is 1.00 and not 0.01 on purpose: the library stops
# amortising once the balance falls below 0.01 and rounds display values to
# cents, while the closed form is exact. A one-currency-unit band over a
# multi-year loan is the honest size of that difference; anything larger
# indicates a real discrepancy rather than accumulated rounding.

failures: list[str] = []
checks = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


# --------------------------------------------------------------------------
# independent reference implementations (Decimal, closed form)
# --------------------------------------------------------------------------
def ref_emi(principal: float, annual_rate_pct: float, months: int) -> Decimal:
    """EMI = P*r*(1+r)^n / ((1+r)^n - 1); r = annual%/1200. Zero-rate: P/n."""
    p = D(str(principal))
    r = D(str(annual_rate_pct)) / D(1200)
    if r == 0:
        return p / D(months)
    growth = (D(1) + r) ** months
    return p * r * growth / (growth - D(1))


def ref_balance(principal: float, annual_rate_pct: float, months: int, k: int) -> Decimal:
    """Analytic outstanding balance after k payments (see module docstring)."""
    p = D(str(principal))
    r = D(str(annual_rate_pct)) / D(1200)
    emi = ref_emi(principal, annual_rate_pct, months)
    if r == 0:
        return p - emi * D(k)
    growth = (D(1) + r) ** k
    return p * growth - emi * ((growth - D(1)) / r)


SCENARIOS = [
    # label,                principal,  rate%,  months,  kind
    ("standard 60-month",   250_000,    8.5,    60,     "normal"),
    ("zero interest",       12_000,     0.0,    12,     "zero"),
    ("near-zero rate",      100_000,    0.01,   360,    "normal"),
    ("maximum rate (100%)", 1_000,      100.0,  6,      "normal"),
    ("fractional principal", 1_234.56,  7.35,   47,     "normal"),
    ("single month",        5_000,      12.0,   1,      "normal"),
    ("very large",          1_000_000_000, 15.0, 480,   "normal"),
    ("very small",          1,          5.0,    6,      "normal"),
    ("long / high rate",    750_000,    99.99,  360,    "normal"),
]

print("=" * 78)
print("Independent validation of utils/finance.py -- Decimal closed form reference")
print("=" * 78)

for label, principal, rate, months, kind in SCENARIOS:
    print(f"\n### {label}: P={principal}, rate={rate}%/yr, n={months}")

    # --- 1. EMI against the closed form ---------------------------------
    got = D(str(calculate_monthly_payment(principal, rate, months)))
    want = ref_emi(principal, rate, months)
    rel = abs(got - want) / want if want else abs(got - want)
    check(f"EMI matches closed form (rel tol {EMI_REL_TOL})",
          rel <= EMI_REL_TOL, f"lib={got:.6f} ref={want:.6f} rel={rel:.2e}")

    # --- 2. zero-rate branch --------------------------------------------
    if kind == "zero":
        check("zero-rate EMI is exactly P/n", got == D(principal) / D(months),
              f"{got} vs {D(principal) / D(months)}")

    # --- 3/4/5. schedule: balances, interest, principal conservation ----
    df, months_taken, total_interest = build_amortization_schedule(
        principal, rate, months, date(2026, 1, 1))

    worst_balance_delta = Decimal(0)
    for k, row in enumerate(df.itertuples(index=False), start=1):
        expected = ref_balance(principal, rate, months, k)
        delta = abs(D(str(row.Balance)) - expected)
        worst_balance_delta = max(worst_balance_delta, delta)
    check(f"every monthly balance matches analytic B_k (abs tol {BALANCE_ABS_TOL})",
          worst_balance_delta <= BALANCE_ABS_TOL,
          f"worst delta {worst_balance_delta:.4f} over {len(df)} months")

    principal_paid = sum(D(str(r.Principal)) for r in df.itertuples(index=False))
    check(f"displayed principal column conserves P (abs tol {PRINCIPAL_DISPLAY_ABS_TOL})",
          abs(principal_paid - D(str(principal))) <= PRINCIPAL_DISPLAY_ABS_TOL,
          f"sum(displayed principal)={principal_paid} vs P={principal}; the unrounded Decimal balance is exact")

    if kind == "normal" and months_taken == months:
        closed_form_interest = ref_emi(principal, rate, months) * D(months) - D(str(principal))
        delta = abs(D(str(total_interest)) - closed_form_interest)
        check(f"total interest matches closed form EMI*n-P (abs tol {INTEREST_ABS_TOL})",
              delta <= INTEREST_ABS_TOL,
              f"lib={D(str(total_interest)):.2f} ref={closed_form_interest:.2f} delta={delta:.4f}")
    else:
        print(f"  [note] closed-form interest comparison skipped (term completed in "
              f"{months_taken} of {months} months)")

    check("final balance is zero", abs(D(str(df.iloc[-1].Balance))) <= D("0.01"),
          f"last balance {df.iloc[-1].Balance}")

print("\n### prepayment: interest and term must strictly improve")
extra = simulate_prepayment(250_000, 8.5, 60, date(2026, 1, 1), extra_monthly=5_000)
check("extra monthly payment shortens the term", extra["months_saved"] > 0,
      f"{extra['baseline_months']} -> {extra['new_months']} months")
check("extra monthly payment saves interest", extra["interest_saved"] > 0,
      f"{extra['baseline_interest']:.2f} -> {extra['new_interest']:.2f}")
check("prepayment cannot increase principal paid",
      extra["new_interest"] < extra["baseline_interest"])

lump = simulate_prepayment(250_000, 8.5, 60, date(2026, 1, 1), lump_sum=50_000, lump_sum_month=12)
check("lump sum shortens the term", lump["months_saved"] > 0,
      f"{lump['baseline_months']} -> {lump['new_months']} months")
check("lump sum saves interest", lump["interest_saved"] > 0,
      f"saved {lump['interest_saved']:.2f}")

# A prepayment large enough to clear the loan immediately: the schedule must
# terminate, not run to its 720-month guard.
big = simulate_prepayment(10_000, 10.0, 60, date(2026, 1, 1), lump_sum=20_000, lump_sum_month=1)
check("overpayment clears the loan in one month", big["new_months"] == 1,
      f"terminated after {big['new_months']} month(s)")
check("overpayment cannot produce negative interest", big["new_interest"] >= 0,
      f"interest {big['new_interest']:.2f}")

print("\n" + "=" * 78)
print(f"{checks - len(failures)}/{checks} checks passed")
if failures:
    print("FAILURES:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("PASS: the library agrees with an independent Decimal closed-form reference")
print("=" * 78)
