"""Tests for utils/servicing.py: golden values, invariants, and validation."""
from datetime import date
from decimal import Decimal

import pytest

from utils.servicing import add_months, annuity_emi, simulate

START = date(2026, 1, 15)
D = Decimal


def assert_invariants(res, principal):
    """Properties every schedule must satisfy, whatever the scenario."""
    assert res.closing_balance == D("0.00")
    # Principal repaid equals the amount borrowed plus capitalised interest.
    repaid = sum((r.principal_paid + r.extra_paid for r in res.rows), D("0"))
    capitalised = sum((r.capitalised for r in res.rows), D("0"))
    assert repaid == q2(D(str(principal)) + capitalised)
    assert res.total_interest == q2(sum((r.interest for r in res.rows), D("0")))
    assert res.total_paid == q2(sum((r.installment_paid + r.extra_paid for r in res.rows), D("0")))
    for r in res.rows:
        assert isinstance(r.interest, Decimal) and isinstance(r.closing, Decimal)
        assert r.closing >= 0
        assert r.opening - r.principal_paid - r.extra_paid + r.capitalised == r.closing


def q2(x):
    return x.quantize(D("0.01"))


def test_golden_emi_and_full_schedule_closes():
    # 10,00,000 at 10% p.a. for 60 months: standard EMI is 21,247.04.
    res = simulate(1_000_000, 10, 60, START)
    assert res.rows[0].installment_paid == D("21247.04")
    assert res.months_taken == 60
    assert res.rows[0].interest == D("8333.33")
    assert res.rows[0].closing == D("987086.29")
    assert_invariants(res, 1_000_000)


def test_zero_rate_splits_principal_evenly():
    res = simulate(1200, 0, 12, START)
    assert all(r.interest == D("0.00") for r in res.rows)
    assert res.rows[0].installment_paid == D("100.00")
    assert res.total_interest == D("0.00")
    assert_invariants(res, 1200)


def test_uneven_division_final_installment_absorbs_rounding():
    res = simulate(1000, 0, 3, START)
    assert [r.installment_paid for r in res.rows] == [D("333.33"), D("333.33"), D("333.34")]
    assert res.closing_balance == D("0.00")


def test_payment_holiday_capitalises_interest_and_extends_maturity():
    res = simulate(1_000_000, 10, 60, START, holidays={2})
    h = res.rows[1]
    assert h.kind == "HOLIDAY"
    assert h.installment_paid == D("0.00")
    assert h.interest == D("8225.72")          # 9,87,086.29 x 10% / 12
    assert h.closing == D("995312.01")         # 9,87,086.29 + 8,225.72
    # Capitalised interest of 8,225.72 stretches the loan to 62 months at the same EMI.
    assert res.months_taken == 62
    emi = D("21247.04")
    assert all(r.installment_paid <= emi for r in res.rows), "no balloon payment"
    assert res.rows[-1].installment_paid < emi  # smaller final installment, not a catch-up
    assert_invariants(res, 1_000_000)


def test_rate_change_recomputes_emi_over_remaining_months():
    res = simulate(1_000_000, 10, 60, START, rate_changes={13: 12})
    row13 = res.rows[12]
    balance_before = res.rows[11].closing
    assert row13.installment_paid == annuity_emi(balance_before, D("12"), 48)
    assert res.months_taken == 60
    assert_invariants(res, 1_000_000)


def test_restructure_shorter_tenure_raises_emi_and_ends_sooner():
    base = simulate(1_000_000, 10, 60, START)
    res = simulate(1_000_000, 10, 60, START, restructures={13: 24})
    assert res.rows[12].installment_paid > base.rows[12].installment_paid
    assert res.months_taken == 24 + 12
    assert_invariants(res, 1_000_000)


def test_extra_payment_shortens_loan_and_saves_interest():
    base = simulate(1_000_000, 10, 60, START)
    res = simulate(1_000_000, 10, 60, START, extra_payments={12: D("50000")})
    assert res.months_taken < base.months_taken
    assert res.total_interest < base.total_interest
    assert res.rows[11].extra_paid == D("50000.00")
    assert_invariants(res, 1_000_000)


def test_extra_payment_larger_than_balance_is_capped():
    res = simulate(1000, 0, 12, START, extra_payments={1: D("5000")})
    assert res.months_taken == 1
    assert res.rows[0].extra_paid == D("916.67")   # 1000 - 83.33 installment
    assert res.closing_balance == D("0.00")


def test_holiday_in_final_scheduled_month_pushes_maturity_out():
    res = simulate(1_000_000, 10, 60, START, holidays={60})
    assert res.rows[-1].kind == "PAYMENT"
    assert res.months_taken == 62
    assert_invariants(res, 1_000_000)


@pytest.mark.parametrize("kwargs", [
    dict(principal=0, annual_rate_pct=10, tenure_months=12),
    dict(principal=1000, annual_rate_pct=-1, tenure_months=12),
    dict(principal=1000, annual_rate_pct=10, tenure_months=0),
    dict(principal=1000, annual_rate_pct=10, tenure_months=721),
])
def test_invalid_inputs_are_rejected(kwargs):
    with pytest.raises(ValueError):
        simulate(start_date=START, **kwargs)


def test_money_is_decimal_not_float():
    res = simulate(1_000_000, 10, 12, START)
    assert isinstance(res.total_interest, Decimal)
    assert isinstance(res.rows[0].installment_paid, Decimal)


def test_add_months_clamps_to_month_end():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)
