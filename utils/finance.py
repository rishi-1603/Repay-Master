"""Core loan-repayment math: EMI, achievements, amortization, prepayment simulation."""
from datetime import timedelta
import pandas as pd


def calculate_monthly_payment(loan_amount, interest_rate, months):
    r = interest_rate / 1200
    if r == 0:
        return loan_amount / months
    return loan_amount * (r * (1 + r) ** months) / ((1 + r) ** months - 1)


def suggest_repayment_period(loan_amount, monthly_income, monthly_expenses, interest_rate):
    annual_income = monthly_income * 12
    disposable_income = monthly_income - monthly_expenses
    loan_to_income_ratio = loan_amount / annual_income

    if loan_to_income_ratio <= 1:
        base_period = 60
    elif loan_to_income_ratio <= 2:
        base_period = 120
    elif loan_to_income_ratio <= 3:
        base_period = 180
    else:
        base_period = 240

    disposable_income_ratio = disposable_income / monthly_income if monthly_income else 0
    if disposable_income_ratio > 0.5:
        base_period = max(base_period * 0.8, 36)
    elif disposable_income_ratio < 0.2:
        base_period = min(base_period * 1.2, 360)

    if interest_rate > 10:
        base_period = min(base_period * 1.1, 360)
    elif interest_rate < 5:
        base_period = max(base_period * 0.9, 36)

    return round(base_period)


def calculate_affordability(monthly_payment, monthly_income, monthly_expenses):
    dti_ratio = monthly_payment / monthly_income if monthly_income else 0
    total_burden = (monthly_payment + monthly_expenses) / monthly_income if monthly_income else 0
    savings_potential = monthly_income - monthly_expenses - monthly_payment

    affordability_score = 0
    if dti_ratio < 0.28:
        affordability_score += 33
    elif dti_ratio < 0.43:
        affordability_score += 20

    if total_burden < 0.7:
        affordability_score += 33
    elif total_burden < 0.8:
        affordability_score += 20

    if savings_potential > monthly_income * 0.2:
        affordability_score += 34
    elif savings_potential > 0:
        affordability_score += 20

    return {
        'dti_ratio': dti_ratio,
        'total_burden': total_burden,
        'savings_potential': savings_potential,
        'affordability_score': affordability_score,
    }


def calculate_achievements(loan_amount, monthly_payment, interest_rate, months):
    """Calculate various achievements and their unlock dates."""
    achievements = []

    time_achievements = {
        3: "Quarter Year Milestone \U0001F331",
        6: "Half Year Champion \U0001F33F",
        12: "One Year Strong \U0001F333",
        24: "Two Year Warrior \U0001F3C6",
        36: "Three Year Victor \U0001F451",
        60: "Five Year Master \U0001F3AF",
        120: "Decade Dedication \U0001F4AB",
    }

    amount_achievements = {
        0.1: "10% Progress Pioneer \U0001F3AF",
        0.25: "Quarter Way Hero \U0001F31F",
        0.5: "Halfway Champion \U0001F3C6",
        0.75: "Three-Quarter Milestone \U0001F4AB",
        0.9: "90% Achievement Unlocked \U0001F451",
        1.0: "Loan Conquered! \U0001F389",
    }

    remaining_balance = loan_amount
    monthly_rate = interest_rate / 1200

    for month in range(1, months + 1):
        interest = remaining_balance * monthly_rate
        principal = monthly_payment - interest
        remaining_balance -= principal

        if month in time_achievements:
            achievements.append({
                'month': month,
                'title': time_achievements[month],
                'type': 'time',
                'description': f"Successfully made payments for {month} months!",
                'amount_paid': loan_amount - remaining_balance,
                'percentage': ((loan_amount - remaining_balance) / loan_amount) * 100,
            })

        progress = (loan_amount - remaining_balance) / loan_amount
        for threshold, title in amount_achievements.items():
            if progress >= threshold and not any(a['title'] == title for a in achievements):
                achievements.append({
                    'month': month,
                    'title': title,
                    'type': 'amount',
                    'description': f"Paid off {threshold * 100:.0f}% of your loan!",
                    'amount_paid': loan_amount - remaining_balance,
                    'percentage': progress * 100,
                })

    return sorted(achievements, key=lambda x: x['month'])


def build_amortization_schedule(loan_amount, interest_rate, months, start_date,
                                 extra_monthly=0, lump_sum=0, lump_sum_month=None):
    """Month-by-month amortization schedule, optionally with extra/lump-sum prepayments.

    Returns (schedule_df, months_taken, total_interest_paid).
    """
    monthly_payment = calculate_monthly_payment(loan_amount, interest_rate, months)
    monthly_rate = interest_rate / 1200

    rows = []
    balance = loan_amount
    month = 0
    total_interest = 0.0

    while balance > 0.01 and month < 720:
        month += 1
        interest = balance * monthly_rate
        principal = monthly_payment - interest
        extra = extra_monthly
        if lump_sum_month and month == int(lump_sum_month):
            extra += lump_sum

        if principal + extra >= balance:
            principal = balance
            extra = 0
            payment = principal + interest
        else:
            payment = monthly_payment + extra

        balance -= (principal + extra)
        total_interest += interest

        rows.append({
            'Month': month,
            'EMI': round(payment, 2),
            'Principal': round(principal + extra, 2),
            'Interest': round(interest, 2),
            'Balance': round(max(balance, 0), 2),
            'Payment Date': (start_date + timedelta(days=30 * month)).strftime('%Y-%m-%d'),
        })

    return pd.DataFrame(rows), month, total_interest


def simulate_prepayment(loan_amount, interest_rate, months, start_date,
                         extra_monthly=0, lump_sum=0, lump_sum_month=None):
    """Compare baseline vs. prepayment scenario. Returns dict of savings."""
    baseline_df, baseline_months, baseline_interest = build_amortization_schedule(
        loan_amount, interest_rate, months, start_date)
    new_df, new_months, new_interest = build_amortization_schedule(
        loan_amount, interest_rate, months, start_date,
        extra_monthly=extra_monthly, lump_sum=lump_sum, lump_sum_month=lump_sum_month)

    return {
        'baseline_months': baseline_months,
        'new_months': new_months,
        'months_saved': baseline_months - new_months,
        'baseline_interest': baseline_interest,
        'new_interest': new_interest,
        'interest_saved': baseline_interest - new_interest,
        'schedule': new_df,
    }
