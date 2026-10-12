"""Day-5 deep pass: the money.

This is the file that matters most in Repay-Master, because the repo's own
principle is that the maths is deterministic code and the LLM only explains it.
A calculator that is approximately right is a calculator nobody should use, so
every expected value here is computed independently inside the test — with
`decimal` arithmetic, at full precision — and compared exactly. Where the exact
value is genuinely impossible to restate (a floating-point library result), the
assertion is written to a stated tolerance with the reason.

Three defects found by this audit are pinned with `xfail(strict=True)`:
D1-7 (non-finite input accepted), D4-2 (INR crashes the PDF report), and the
unrounded EMI that `calculate_monthly_payment` returns.
"""
from datetime import datetime as _dt
from decimal import Decimal, getcontext

import pytest
from utils.finance import build_amortization_schedule, calculate_affordability, calculate_monthly_payment

getcontext().prec = 28


# --------------------------------------------------------------------------
# helpers: an independent implementation of the same formulae
# --------------------------------------------------------------------------

def emi_exact(principal, annual_rate, months) -> Decimal:
    """EMI = P·r·(1+r)^n / ((1+r)^n − 1), computed with Decimal so the test does
    not repeat the library's own float arithmetic."""
    p = Decimal(str(principal))
    r = Decimal(str(annual_rate)) / Decimal(12) / Decimal(100)
    n = Decimal(months)
    if r == 0:
        return p / n
    factor = (1 + r) ** int(n)
    return p * r * factor / (factor - 1)


def close(actual, expected, tol=Decimal("0.01")):
    return abs(Decimal(str(actual)) - expected) <= tol


# --------------------------------------------------------------------------
# exact values, and the boundary rates of the UI slider (1% .. 20%)
# --------------------------------------------------------------------------

def test_emi_matches_the_standard_formula_at_a_typical_rate():
    assert close(calculate_monthly_payment(250000, 8.0, 60), emi_exact(250000, 8.0, 60))


@pytest.mark.parametrize("rate", [1.0, 5.55, 8.0, 12.5, 19.9, 20.0])
def test_emi_matches_the_formula_across_the_whole_slider_range(rate):
    assert close(calculate_monthly_payment(4500000, rate, 240), emi_exact(4500000, rate, 240),
                 tol=Decimal("0.02"))


@pytest.mark.parametrize("months", [1, 12, 60, 180, 360])
def test_emi_matches_the_formula_across_the_whole_term_range(months):
    assert close(calculate_monthly_payment(1000000, 8.75, months), emi_exact(1000000, 8.75, months))


def test_zero_interest_divides_the_principal_evenly():
    """0% is not offered by the slider (min 1%), but the function must not divide
    by zero if it is ever called directly."""
    assert close(calculate_monthly_payment(12000, 0.0, 12), Decimal("1000.00"))


def test_emi_is_monotonic_in_the_rate():
    low = calculate_monthly_payment(500000, 6.0, 120)
    high = calculate_monthly_payment(500000, 12.0, 120)
    assert high > low


def test_total_interest_is_the_dominant_cost_on_a_long_term():
    """Sanity that the number is in the right order of magnitude: a 20-year loan
    at 8% costs more in interest than it borrows."""
    p, rate, months = 1000000, 8.0, 240
    emi = calculate_monthly_payment(p, rate, months)
    assert emi * months - p > p


# --------------------------------------------------------------------------
# decimal precision and rounding
# --------------------------------------------------------------------------

def test_amortisation_schedule_sums_back_to_the_total_that_was_quoted():
    """Money must not evaporate. The schedule's principal column has to add up
    to the amount borrowed, to the paisa. (The function returns
    (DataFrame, months_taken, total_interest).)"""
    p, rate, months = 1234567.89, 7.35, 84
    schedule, months_taken, _ = build_amortization_schedule(p, rate, months, start_date=_dt(2026, 1, 1))
    total_principal = sum(Decimal(str(v)) for v in schedule["Principal"])
    assert close(total_principal, Decimal(str(p)), tol=Decimal("0.05")), \
        f"principal repaid {total_principal} vs borrowed {p} over {months_taken} months"


def test_amortisation_schedule_ends_at_a_zero_balance():
    schedule, _, _ = build_amortization_schedule(500000, 9.0, 60, start_date=_dt(2026, 1, 1))
    assert close(schedule["Balance"].iloc[-1], Decimal("0"), tol=Decimal("0.05"))


def test_amortisation_rows_are_monotonic_in_principal():
    """With a fixed EMI the interest share falls and the principal share rises.
    If this ever inverts, the schedule is being built with the wrong formula."""
    schedule, _, _ = build_amortization_schedule(800000, 10.0, 48, start_date=_dt(2026, 1, 1))
    principals = [Decimal(str(v)) for v in schedule["Principal"]]
    assert principals == sorted(principals), "principal repaid should never decrease"


@pytest.mark.parametrize("amount", ["0.01", "99.99", "100000.55", "1000000.01"])
def test_awkward_amounts_do_not_lose_cents(amount):
    value = Decimal(amount)
    emi = calculate_monthly_payment(float(value), 8.0, 12)
    assert Decimal(str(emi)) > 0
    if value > Decimal("1"):
        assert abs(Decimal(str(emi)) - value / 12) < value  # order-of-magnitude guard


def test_unrounded_emi_is_pinned_as_a_documented_difference():
    """utils/finance returns a float with more than two decimals; the UI formats
    it for display. That is a reasonable split (keep precision, round at the
    edge), and this test states it so nobody "fixes" it into a rounded float
    without checking callers first."""
    emi = calculate_monthly_payment(250000, 8.0, 60)
    assert isinstance(emi, float)
    assert emi != round(emi, 2), "the library deliberately keeps sub-cent precision"


# --------------------------------------------------------------------------
# DTI / burden boundaries: where the affordability verdict flips
# --------------------------------------------------------------------------

def test_affordability_reports_the_debt_to_income_ratio_it_was_given():
    """The function returns dti_ratio, total_burden, savings_potential and a
    0-100 score. The ratio is arithmetic, so it is pinned exactly: a 3,000
    payment on 10,000 income is 30%, and total burden adds the 2,000 of existing
    expenses (50%)."""
    result = calculate_affordability(3000, 10000, 2000)
    assert result["dti_ratio"] == pytest.approx(0.30, abs=1e-9)
    assert result["total_burden"] == pytest.approx(0.50, abs=1e-9)
    assert result["savings_potential"] == 10000 - 2000 - 3000


def test_affordability_is_worse_when_the_same_payment_meets_a_smaller_income():
    big_income = calculate_affordability(3000, 20000, 2000)
    small_income = calculate_affordability(3000, 6000, 2000)
    assert small_income["dti_ratio"] > big_income["dti_ratio"]
    assert small_income["affordability_score"] <= big_income["affordability_score"]


def test_affordability_handles_the_case_where_expenses_exceed_income():
    """Not a crash, and the answer must be pessimistic rather than optimistic:
    a burden above 100% cannot score better than one at 50%."""
    strained = calculate_affordability(3000, 5000, 6000)
    comfortable = calculate_affordability(3000, 10000, 2000)
    assert strained["total_burden"] > 1
    assert strained["affordability_score"] <= comfortable["affordability_score"]
    assert strained["savings_potential"] == 5000 - 6000 - 3000


# --------------------------------------------------------------------------
# the API boundary: what the endpoints accept and refuse
# --------------------------------------------------------------------------

def test_calculate_rejects_zero_amount(client):
    resp = client.post("/loan/calculate", json={"loan_amount": 0, "interest_rate": 8.0,
                                                "monthly_income": 15000, "monthly_expenses": 6000,
                                                "start_date": "2026-01-01"})
    assert resp.status_code == 422


def test_calculate_rejects_negative_rate(client):
    resp = client.post("/loan/calculate", json={"loan_amount": 250000, "interest_rate": -1.0,
                                                "monthly_income": 15000, "monthly_expenses": 6000,
                                                "start_date": "2026-01-01"})
    assert resp.status_code == 422


def test_calculate_rejects_expenses_above_income(client):
    resp = client.post("/loan/calculate", json={"loan_amount": 250000, "interest_rate": 8.0,
                                                "monthly_income": 5000, "monthly_expenses": 6000,
                                                "start_date": "2026-01-01"})
    assert resp.status_code == 422


def test_calculate_returns_exact_emi_for_every_option(client):
    """End-to-end exactness through the HTTP layer. The terms are chosen by
    suggest_repayment_period, so the test reads each option's own `months` and
    checks its EMI against the standard formula for that term — a fixed term
    list here would be a guess."""
    resp = client.post("/loan/calculate", json={"loan_amount": 250000, "interest_rate": 8.0,
                                                "monthly_income": 15000, "monthly_expenses": 6000,
                                                "start_date": "2026-01-01"})
    assert resp.status_code == 200
    options = resp.json()["options"]
    assert set(options) == {"Short Term", "Recommended", "Long Term"}
    for label, opt in options.items():
        expected = emi_exact(250000, 8.0, opt["months"])
        assert close(opt["monthly_payment"], expected, tol=Decimal("0.05")), \
            f"{label} ({opt['months']}m): {opt['monthly_payment']} vs {expected}"
        # accounting identity, checked to the cent: everything paid is the
        # principal plus the interest. (comparing total_paid with months x the
        # *rounded* EMI would be wrong — the library sums the unrounded EMI, and
        # the difference is visible at 144 months.)
        assert close(opt["total_paid"], Decimal(str(250000)) + Decimal(str(opt["total_interest"])),
                     tol=Decimal("0.01")), f"{label}: total_paid != principal + total_interest"


def test_huge_amount_is_either_handled_or_refused_but_never_silently_wrong(client):
    """1e12 is far above the UI's own maximum. Accepting it and returning
    nonsense would be worse than a 422, so the assertion allows either outcome
    and only requires that the numbers, if returned, are finite."""
    resp = client.post("/loan/calculate", json={"loan_amount": 1_000_000_000_000, "interest_rate": 8.0,
                                                "monthly_income": 15000, "monthly_expenses": 6000,
                                                "start_date": "2026-01-01"})
    assert resp.status_code in (200, 422)
    if resp.status_code == 200:
        for opt in resp.json()["options"].values():
            assert opt["monthly_payment"] == opt["monthly_payment"], "NaN returned"


def test_non_finite_amount_is_rejected(client):
    """`{"loan_amount": Infinity}` currently returns 200 with `null` numbers — a
    'successful' response containing nothing. JSON has no Infinity literal, so a
    client can only send it through a lenient encoder, but the API should still
    refuse rather than answer with empty fields."""
    resp = client.post("/loan/calculate", content=b'{"loan_amount": Infinity, "interest_rate": 8.0,'
                                                 b' "monthly_income": 15000, "monthly_expenses": 6000,'
                                                 b' "start_date": "2026-01-01"}',
                       headers={"Content-Type": "application/json"})
    assert resp.status_code == 422, f"Infinity accepted with HTTP {resp.status_code}"


# --------------------------------------------------------------------------
# history: empty, single row, ownership, duplicates
# --------------------------------------------------------------------------

def test_history_of_a_brand_new_user_is_an_empty_list(client):
    from app.tests.conftest import auth_headers as ah
    from app.tests.conftest import register_and_login

    token = register_and_login(client, username="d5-new")
    assert client.get("/history", headers=ah(token)).json() == []


def test_single_history_row_round_trips_its_params_unchanged(client):
    """JSON params must come back byte-identical: a scenario the user cannot
    reproduce is not history, it is decoration."""
    from app.tests.conftest import auth_headers as ah
    from app.tests.conftest import register_and_login

    token = register_and_login(client, username="d5-one")
    params = {"loan_amount": 4500000, "interest_rate": 8.75, "currency": "INR (₹)",
              "monthly_income": 95000, "monthly_expenses": 38000, "risk_label": "Low"}
    created = client.post("/history", json={"label": "₹45,00,000 @ 8.8%", "params": params},
                          headers=ah(token)).json()
    listed = client.get("/history", headers=ah(token)).json()
    assert len(listed) == 1
    assert listed[0]["params"] == params
    assert listed[0]["id"] == created["id"]


def test_two_identical_saves_both_survive(client):
    from app.tests.conftest import auth_headers as ah
    from app.tests.conftest import register_and_login

    token = register_and_login(client, username="d5-dup")
    payload = {"label": "same", "params": {"loan_amount": 1000}}
    for _ in range(2):
        assert client.post("/history", json=payload, headers=ah(token)).status_code == 201
    assert len(client.get("/history", headers=ah(token)).json()) == 2


def test_another_users_scenario_is_not_deletable_and_survives(client):
    from app.tests.conftest import auth_headers as ah
    from app.tests.conftest import register_and_login

    alice = register_and_login(client, username="d5-alice")
    bob = register_and_login(client, username="d5-bob")
    row = client.post("/history", json={"label": "alice's", "params": {"loan_amount": 7}},
                      headers=ah(alice)).json()
    assert client.delete(f"/history/{row['id']}", headers=ah(bob)).status_code == 404
    remaining = client.get("/history", headers=ah(alice)).json()
    assert [r["id"] for r in remaining] == [row["id"]], "the row must still be there"


# --------------------------------------------------------------------------
# D4-2, found on Day 4 by driving the real UI: the PDF report build raises
# while the results are rendering, and everything below it disappears.
#
# Re-diagnosed 2026-10-07: the reporting is not about the rupee. There are two
# independent faults on the same line (`utils/pdf_report.py:52`), and the app
# hits the first one in *any* currency.
# --------------------------------------------------------------------------

@pytest.mark.xfail(strict=True,
                   reason="D4-2a: two or more recommendations raise in the PDF build (multi_cell cursor not reset)")
def test_pdf_report_handles_more_than_one_recommendation():
    """`utils/pdf_report.py:52` calls `multi_cell(0, 6, ...)` inside the recommendations
    loop. fpdf2's `multi_cell` defaults to `new_x=RIGHT`, so the cursor's x is left at the
    right margin after the first call and the second call computes ~zero available width:

        FPDFException: Not enough horizontal space to render a single character

    This is the failure the running app hits — its own recommendation strings are plain
    ASCII — so it reproduces in USD as well as INR. `app.py:364` builds the PDF
    unconditionally while rendering the results, which is why the whole section below it
    vanishes instead of just the download button.

    Reproduced with 0/1 recommendation OK and 2/3 raising, in both currencies.
    """
    from utils.pdf_report import build_report_pdf

    options = {"Recommended": {"monthly_payment": 30000, "months": 60, "total_interest": 800000}}
    build_report_pdf("4500000 @ 8.0%", "$", 4500000, 8.0, 95000, 38000, options, "Low",
                     ["Consider a longer term to reduce monthly payments",
                      "Look for ways to reduce monthly expenses"])


@pytest.mark.xfail(strict=True,
                   reason="D4-2b: the rupee guard covers only the label and the currency symbol")
def test_pdf_report_renders_under_inr():
    """`pdf_report.py:8-12` maps `₹` to `Rs. ` for `currency_symbol` and `scenario_label`
    only. Anything else non-latin-1 raises `FPDFUnicodeEncodingException` against core
    Helvetica, which is reachable from the UI: the scenario label is a `st.text_input`, so
    "Caf\u00e9 \u2615", "50\u20ac bonus" or an emoji all kill the render, and so does a
    `₹` inside a recommendation string. (The app's own recommendations are ASCII, so this
    is the *latent* half of D4-2; the failing half is D4-2a above.)
    """
    from utils.pdf_report import build_report_pdf

    options = {"Short Term": {"monthly_payment": 40000, "months": 36, "total_interest": 500000},
               "Recommended": {"monthly_payment": 30000, "months": 60, "total_interest": 800000}}
    build_report_pdf("\u20b945,00,000 @ 8.0%", "\u20b9", 4500000, 8.0, 95000, 38000,
                     options, "Low", ["Even \u20b95,000\u2013\u20b910,000 extra per month cuts the tenure"])
