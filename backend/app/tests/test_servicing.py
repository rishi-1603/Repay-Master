"""Engine tests for utils/servicing.py: golden values, invariants, validation."""
from datetime import date
from decimal import Decimal

import pytest
from utils.servicing import (
    add_months,
    annuity_emi,
    compare_scenarios,
    foreclosure_quote,
    monthly_series,
    simulate,
)

START = date(2026, 1, 15)
D = Decimal
EMI_10L_10PCT_60M = D("21247.04")


def assert_invariants(res, principal):
    """Properties every schedule must satisfy, whatever the scenario."""
    assert res.closing_balance == D("0.00")
    assert res.maturity_date == res.rows[-1].due_date
    for r in res.rows:
        assert all(isinstance(x, Decimal) for x in (r.interest, r.installment_paid, r.closing))
        assert r.closing >= 0
        assert r.closing == r.opening + r.interest + r.fee_charged - r.installment_paid - r.extra_paid
    total_interest = sum((r.interest for r in res.rows), D("0"))
    total_fees = sum((r.fee_charged for r in res.rows), D("0"))
    total_paid = sum((r.installment_paid + r.extra_paid for r in res.rows), D("0"))
    assert res.total_interest == total_interest.quantize(D("0.01"))
    assert res.total_late_fees == total_fees.quantize(D("0.01"))
    assert res.total_paid == total_paid.quantize(D("0.01"))
    # Money conservation: everything paid = principal + interest + late fees.
    assert res.total_paid == D(str(principal)) + res.total_interest + res.total_late_fees


def test_golden_emi_and_full_schedule_closes():
    res = simulate(1_000_000, 10, 60, START)
    assert res.rows[0].installment_paid == EMI_10L_10PCT_60M
    assert res.months_taken == 60
    assert res.rows[0].interest == D("8333.33")
    assert res.rows[0].closing == D("987086.29")
    assert res.maturity_date == date(2031, 1, 15)
    assert_invariants(res, 1_000_000)


def test_emi_matches_independent_float_formula_within_a_paisa():
    r = 0.10 / 12
    f = (1 + r) ** 60
    expected = 1_000_000 * r * f / (f - 1)
    assert abs(float(EMI_10L_10PCT_60M) - expected) < 0.01


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


def test_balance_after_month_twelve_matches_closed_form():
    # Independent check: B_n = P(1+r)^n - EMI*((1+r)^n - 1)/r, within a rupee of cent rounding.
    res = simulate(1_000_000, 10, 60, START)
    r = 0.10 / 12
    f = (1 + r) ** 12
    closed = 1_000_000 * f - 21247.0447 * (f - 1) / r
    assert abs(float(res.balance_after(12)) - closed) < 1.0


def test_payment_holiday_capitalises_interest_and_extends_maturity():
    res = simulate(1_000_000, 10, 60, START, holidays={2})
    h = res.rows[1]
    assert h.kind == "HOLIDAY" and h.installment_paid == D("0.00")
    assert h.interest == D("8225.72")
    assert h.closing == D("995312.01")
    assert res.months_taken == 62            # capitalised interest extends the loan
    assert all(r.installment_paid <= EMI_10L_10PCT_60M for r in res.rows), "no balloon payment"
    assert res.rows[-1].installment_paid < EMI_10L_10PCT_60M
    assert_invariants(res, 1_000_000)


def test_six_month_deferment_pushes_maturity_out_by_six_months():
    res = simulate(1_000_000, 10, 60, START, holidays=set(range(1, 7)))
    assert res.months_taken > 60 + 6 - 1
    assert res.total_interest > simulate(1_000_000, 10, 60, START).total_interest
    assert_invariants(res, 1_000_000)


def test_rate_change_recomputes_emi_over_remaining_months():
    res = simulate(1_000_000, 10, 60, START, rate_changes={13: 12})
    balance_before = res.rows[11].closing
    assert res.rows[12].installment_paid == annuity_emi(balance_before, D("12"), 48)
    assert res.months_taken == 60
    assert_invariants(res, 1_000_000)


def test_rate_increase_costs_more_interest():
    base = simulate(1_000_000, 10, 60, START)
    up = simulate(1_000_000, 10, 60, START, rate_changes={1: 11})
    assert up.total_interest > base.total_interest
    assert_invariants(up, 1_000_000)


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


def test_partial_payment_charges_late_fee_once_and_extends_loan():
    res = simulate(1_000_000, 10, 60, START, partial_payments={5: D("10000")}, late_fee=500)
    row = res.rows[4]
    assert row.installment_paid == D("10000.00")
    assert row.fee_charged == D("500.00")
    assert "partial payment" in row.event and "late fee" in row.event
    assert res.total_late_fees == D("500.00")
    assert res.months_taken > 60
    assert_invariants(res, 1_000_000)


def test_partial_payment_below_interest_grows_the_balance():
    res = simulate(1_000_000, 10, 60, START, partial_payments={1: D("1000")})
    assert res.rows[0].installment_paid == D("1000.00")
    assert res.rows[0].closing > D("1000000.00")   # unpaid interest rolls onto the balance
    assert_invariants(res, 1_000_000)


def test_partial_payment_above_installment_is_capped_at_installment_due():
    base = simulate(1_000_000, 10, 60, START)
    res = simulate(1_000_000, 10, 60, START, partial_payments={3: D("999999")})
    assert res.rows[2].installment_paid == base.rows[2].installment_paid
    assert res.total_late_fees == D("0.00")


def test_processing_fee_is_upfront_cost_not_added_to_balance():
    base = simulate(1_000_000, 10, 60, START)
    res = simulate(1_000_000, 10, 60, START, processing_fee_pct=1)
    assert res.processing_fee == D("10000.00")
    assert res.total_paid == base.total_paid
    assert res.total_cost == base.total_interest + D("10000.00")


def test_holiday_cannot_also_carry_extra_or_partial_payment():
    with pytest.raises(ValueError, match="cannot also carry a payment"):
        simulate(1_000_000, 10, 60, START, holidays={2}, extra_payments={2: D("100")})
    with pytest.raises(ValueError, match="cannot also carry a payment"):
        simulate(1_000_000, 10, 60, START, holidays={2}, partial_payments={2: D("100")})


@pytest.mark.parametrize("kwargs", [
    dict(principal=0, annual_rate_pct=10, tenure_months=12),
    dict(principal=1000, annual_rate_pct=-1, tenure_months=12),
    dict(principal=1000, annual_rate_pct=10, tenure_months=0),
    dict(principal=1000, annual_rate_pct=10, tenure_months=721),
    dict(principal=1000, annual_rate_pct=10, tenure_months=12, late_fee=-1),
    dict(principal=1000, annual_rate_pct=10, tenure_months=12, processing_fee_pct=-1),
    dict(principal=1000, annual_rate_pct=10, tenure_months=12, partial_payments={1: -5}),
    dict(principal=1000, annual_rate_pct=10, tenure_months=12, restructures={2: 0}),
])
def test_invalid_inputs_are_rejected(kwargs):
    with pytest.raises(ValueError):
        simulate(start_date=START, **kwargs)


def test_money_is_decimal_not_float():
    res = simulate(1_000_000, 10, 12, START)
    assert isinstance(res.total_interest, Decimal)
    assert isinstance(res.rows[0].installment_paid, Decimal)


def test_foreclosure_quote_before_first_installment():
    quote = foreclosure_quote(1_000_000, 10, 60, START, month=1, foreclosure_charge_pct=2)
    assert quote["outstanding_principal"] == "1000000.00"
    assert quote["accrued_interest"] == "8333.33"
    assert quote["foreclosure_charge"] == "20000.00"
    assert quote["total_payable"] == "1028333.33"


def test_foreclosure_quote_after_a_year_uses_outstanding_balance():
    res = simulate(1_000_000, 10, 60, START)
    quote = foreclosure_quote(1_000_000, 10, 60, START, month=13)
    assert quote["outstanding_principal"] == str(res.balance_after(12))


def test_foreclosure_quote_after_closure_is_refused():
    with pytest.raises(ValueError, match="already closed"):
        foreclosure_quote(1000, 0, 3, START, month=5)


def test_compare_scenarios_matches_the_roadmap_example():
    scenarios = {
        "extra_2000_monthly": {"extra_payments": monthly_series(2000, 1, 60)},
        "lump_50000_yearly": {"extra_payments": monthly_series(50000, 12, 60, every=12)},
        "defer_six_months": {"holidays": set(range(1, 7))},
        "rate_plus_one_point": {"rate_changes": {1: 11}},
    }
    out = compare_scenarios(1_000_000, 10, 60, START, scenarios)
    assert out["baseline"]["months_saved_vs_baseline"] == 0
    assert out["extra_2000_monthly"]["months_saved_vs_baseline"] > 0
    assert out["lump_50000_yearly"]["months_saved_vs_baseline"] > 0
    assert out["defer_six_months"]["months_saved_vs_baseline"] < 0
    assert Decimal(out["rate_plus_one_point"]["interest_saved_vs_baseline"]) < 0
    assert out["baseline"]["maturity_date"] == "2031-01-15"


def test_add_months_clamps_to_month_end():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)
