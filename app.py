import os
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import google.generativeai as genai

from utils.auth import authenticate, register_user, save_scenario, get_saved_scenarios, delete_scenario
from utils.currency import get_usd_inr_rate, symbol, format_amount
from utils.finance import (
    calculate_monthly_payment, suggest_repayment_period, calculate_affordability,
    calculate_achievements, build_amortization_schedule, simulate_prepayment,
)
from utils.risk import load_risk_model, load_model_metrics, predict_risk, explain_prediction
from utils.pdf_report import build_report_pdf

LIGHT_BLUE = "#7EC8F5"
DARK_BLUE = "#1f4e8c"

st.set_page_config(page_title="RepayMaster — Loan Repayment Timeline Predictor",
                    page_icon="🏦", layout="wide")

# ----------------------------------------------------------------------------
# Sidebar: Account (login / register / saved history gate)
# ----------------------------------------------------------------------------
if "username" not in st.session_state:
    st.session_state.username = None

with st.sidebar:
    st.header("Account")
    if st.session_state.username:
        st.success(f"Logged in as {st.session_state.username}")
        if st.button("Log out"):
            st.session_state.username = None
            st.rerun()
    else:
        tab_login, tab_register = st.tabs(["Log in", "Register"])
        with tab_login:
            login_user = st.text_input("Username", key="login_user")
            login_pass = st.text_input("Password", type="password", key="login_pass")
            if st.button("Log in"):
                ok, msg = authenticate(login_user, login_pass)
                if ok:
                    st.session_state.username = login_user.strip()
                    st.rerun()
                else:
                    st.error(msg)
        with tab_register:
            reg_user = st.text_input("Username", key="reg_user")
            reg_pass = st.text_input("Password", type="password", key="reg_pass")
            reg_pass2 = st.text_input("Confirm password", type="password", key="reg_pass2")
            if st.button("Register"):
                if reg_pass != reg_pass2:
                    st.error("Passwords do not match.")
                else:
                    ok, msg = register_user(reg_user, reg_pass)
                    (st.success if ok else st.error)(msg)
        st.caption("Log in to save loan scenarios and view your history. "
                   "The calculator works fully without an account too.")

# ----------------------------------------------------------------------------
# Header
# ----------------------------------------------------------------------------
st.title("🏦 RepayMaster — Loan Repayment Timeline Predictor")
st.caption("EMI calculator + ML-based affordability risk predictor")
st.divider()

# ----------------------------------------------------------------------------
# Currency selection
# ----------------------------------------------------------------------------
currency = st.radio("Select Currency", ["USD ($)", "INR (₹)"], horizontal=True,
                     help="Switch the calculator's units between US Dollars and Indian Rupees.")
currency = "INR" if currency.startswith("INR") else "USD"
cur_sym = symbol(currency)

if currency == "INR":
    st.info("🇮🇳 Indian Rupee mode — amounts displayed in ₹. Large values shown in Lakhs (L) and Crores (Cr).")

rate, is_live = get_usd_inr_rate()
with st.expander("🔄 Live exchange rate"):
    status = "🟢 live" if is_live else "🔴 offline (cached estimate)"
    st.write(f"1 USD ≈ {rate:.2f} INR — {status}")

st.divider()

# ----------------------------------------------------------------------------
# Main inputs
# ----------------------------------------------------------------------------
col1, col2 = st.columns(2)

if currency == "USD":
    loan_min, loan_max, loan_default, loan_step = 1000, 1_000_000, 250_000, 1000
    income_min, income_max, income_default, income_step = 1000, 100_000, 15_000, 100
    expense_step = 100
else:
    loan_min, loan_max, loan_default, loan_step = 100_000, 100_000_000, 2_000_000, 10_000
    income_min, income_max, income_default, income_step = 10_000, 10_000_000, 100_000, 1000
    expense_step = 1000

with col1:
    st.subheader("Loan Details")
    loan_amount = st.number_input(f"Loan Amount ({cur_sym})", min_value=loan_min, max_value=loan_max,
                                   value=loan_default, step=loan_step)
    interest_rate = st.slider("Interest Rate (%)", min_value=1.0, max_value=20.0, value=8.0, step=0.1)
    start_date = st.date_input("Start Date", datetime.now())

with col2:
    st.subheader("Financial Information")
    monthly_income = st.number_input(f"Monthly Income ({cur_sym})", min_value=income_min,
                                      max_value=income_max, value=income_default, step=income_step)
    monthly_expenses = st.number_input(f"Monthly Expenses ({cur_sym})", min_value=0,
                                        max_value=int(monthly_income), step=expense_step,
                                        value=min(int(monthly_income * 0.4), int(monthly_income)))

calculate_clicked = st.button("Calculate Repayment Options", type="primary")

if calculate_clicked:
    st.session_state.results_ready = True
    st.session_state.loan_amount = loan_amount
    st.session_state.interest_rate = interest_rate
    st.session_state.monthly_income = monthly_income
    st.session_state.monthly_expenses = monthly_expenses
    st.session_state.start_date = start_date
    st.session_state.currency = currency

if st.session_state.get("results_ready"):
    loan_amount = st.session_state.loan_amount
    interest_rate = st.session_state.interest_rate
    monthly_income = st.session_state.monthly_income
    monthly_expenses = st.session_state.monthly_expenses
    start_date = st.session_state.start_date
    currency = st.session_state.currency
    cur_sym = symbol(currency)

    suggested_months = suggest_repayment_period(loan_amount, monthly_income, monthly_expenses, interest_rate)
    terms = {
        'Short': max(suggested_months - 60, 36),
        'Recommended': suggested_months,
        'Long': min(suggested_months + 60, 360),
    }

    options = {}
    for term_name, months in terms.items():
        monthly_payment = calculate_monthly_payment(loan_amount, interest_rate, months)
        total_interest = (monthly_payment * months) - loan_amount
        affordability = calculate_affordability(monthly_payment, monthly_income, monthly_expenses)
        options[term_name] = {
            'months': months,
            'monthly_payment': monthly_payment,
            'total_interest': total_interest,
            'affordability': affordability,
        }
    recommended = options['Recommended']

    # ------------------------------------------------------------------
    # 1. Monthly EMI Comparison
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("📈 Monthly EMI Comparison")
    fig = go.Figure(go.Bar(
        x=list(options.keys()),
        y=[d['monthly_payment'] for d in options.values()],
        text=[f"{cur_sym}{d['monthly_payment']:,.0f}" for d in options.values()],
        textposition="outside",
        marker_color=LIGHT_BLUE,
        name="Monthly EMI",
    ))
    fig.update_layout(template="plotly_dark", yaxis_title=f"Amount ({cur_sym})", showlegend=True)
    st.plotly_chart(fig, use_container_width=True)

    # ------------------------------------------------------------------
    # 2. Breakdown + Cash flow
    # ------------------------------------------------------------------
    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        st.markdown("**Total Payment Breakdown**")
        fig_pie = go.Figure(go.Pie(
            labels=["Principal", "Interest"],
            values=[loan_amount, recommended['total_interest']],
            hole=0.5,
            marker_colors=[LIGHT_BLUE, DARK_BLUE],
        ))
        fig_pie.update_layout(template="plotly_dark")
        st.plotly_chart(fig_pie, use_container_width=True)
    with chart_col2:
        st.markdown("**Monthly Cash Flow Analysis**")
        cash_flow_data = pd.DataFrame({
            'Category': ['Income', 'Expenses', 'Loan EMI', 'Remaining'],
            'Amount': [
                monthly_income, monthly_expenses, recommended['monthly_payment'],
                monthly_income - monthly_expenses - recommended['monthly_payment'],
            ],
        })
        fig_bar = px.bar(cash_flow_data, x='Category', y='Amount', template="plotly_dark",
                          color_discrete_sequence=[LIGHT_BLUE])
        st.plotly_chart(fig_bar, use_container_width=True)

    # ------------------------------------------------------------------
    # 3. ML Risk Assessment
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("🧠 ML Risk Assessment")
    metrics = load_model_metrics()
    acc_text = f"{metrics['test_accuracy']}%" if metrics.get("test_accuracy") else "N/A"
    st.caption(f"Predicted by a RandomForest model (v2.0.0) trained on synthetic loan data — "
               f"estimates affordability risk from the same inputs above. "
               f"Test-set accuracy: {acc_text}. See `MODEL_CARD.md` for details and limitations.")

    risk_model, risk_scaler = load_risk_model()
    features = {
        "loan_amount": loan_amount, "interest_rate": interest_rate,
        "monthly_income": monthly_income, "monthly_expenses": monthly_expenses,
        "monthly_payment": recommended['monthly_payment'],
    }
    risk_label, proba_dict = predict_risk(risk_model, risk_scaler, features)
    risk_emoji = {"Low": "🟢", "Medium": "🟡", "High": "🔴"}.get(risk_label, "⚪")
    st.markdown(f"### Predicted Risk Level: {risk_emoji} {risk_label}")

    st.markdown("**Model Confidence by Risk Category**")
    order = ["High", "Low", "Medium"]
    classes = [c for c in order if c in proba_dict] + [c for c in proba_dict if c not in order]
    fig_conf = go.Figure(go.Bar(x=classes, y=[proba_dict[c] for c in classes], marker_color=LIGHT_BLUE))
    fig_conf.update_layout(template="plotly_dark", yaxis_title="Probability", xaxis_title="Risk Level")
    st.plotly_chart(fig_conf, use_container_width=True)

    with st.expander("Why did the model predict this? (SHAP explanation)"):
        explain_df = explain_prediction(risk_model, risk_scaler, features)
        if explain_df["approximate"].iloc[0]:
            st.caption("(Approximate — SHAP unavailable, showing global feature importance instead.)")
        fig_shap = px.bar(explain_df, x="contribution", y="feature", orientation="h",
                           template="plotly_dark", color_discrete_sequence=[LIGHT_BLUE])
        st.plotly_chart(fig_shap, use_container_width=True)

    # ------------------------------------------------------------------
    # 4. Financial Health Analysis
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("💹 Financial Health Analysis")
    health_cols = st.columns(3)
    dti = recommended['affordability']['dti_ratio']
    burden = recommended['affordability']['total_burden']
    savings = recommended['affordability']['savings_potential']
    with health_cols[0]:
        st.metric("Debt-to-Income Ratio", f"{dti * 100:.1f}%", "Good" if dti < 0.43 else "High")
    with health_cols[1]:
        st.metric("Total Monthly Burden", f"{burden * 100:.1f}%", "Good" if burden < 0.8 else "High")
    with health_cols[2]:
        st.metric("Monthly Savings Potential", format_amount(savings, currency), "After loan payment")

    # ------------------------------------------------------------------
    # 5. Achievements
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("🏆 Loan Payment Achievements")
    term_tabs = st.tabs(list(options.keys()))
    for tab, term_name in zip(term_tabs, options.keys()):
        with tab:
            data = options[term_name]
            achievements = calculate_achievements(loan_amount, data['monthly_payment'], interest_rate, data['months'])

            fig_ach = go.Figure()
            months_range = list(range(0, data['months'] + 1))
            progress = [min(100 * i * data['monthly_payment'] / loan_amount, 100) for i in months_range]
            fig_ach.add_trace(go.Scatter(x=months_range, y=progress, mode='lines',
                                          line=dict(color='rgba(126,200,245,0.4)'), name='Loan Progress'))
            fig_ach.add_trace(go.Scatter(
                x=[a['month'] for a in achievements],
                y=[a['percentage'] for a in achievements],
                mode='markers+text',
                marker=dict(size=16, symbol='star',
                            color=['gold' if a['type'] == 'amount' else 'silver' for a in achievements]),
                text=[a['title'].split()[0] for a in achievements],
                textposition='top center',
                name='Achievements',
            ))
            fig_ach.update_layout(template="plotly_dark", title=f"Achievement Timeline — {term_name} Term",
                                   xaxis_title="Months", yaxis_title="Loan Progress (%)",
                                   yaxis_range=[0, 105], showlegend=True)
            st.plotly_chart(fig_ach, use_container_width=True)

            with st.expander("View Detailed Achievements"):
                for a in achievements:
                    st.markdown(f"""
**{a['title']}**
- 📅 Month: {a['month']} ({a['month'] / 12:.1f} years)
- 💰 Amount Paid: {format_amount(a['amount_paid'], currency)}
- 📊 Progress: {a['percentage']:.1f}%
- 📝 {a['description']}
---
""")

            upcoming = next((a for a in achievements if a['month'] > 1), None)
            if upcoming:
                months_until = upcoming['month'] - 1
                st.info(f"**{upcoming['title']}** — unlocks in {months_until} months "
                        f"({upcoming['percentage']:.1f}% done, {format_amount(upcoming['amount_paid'], currency, compact=True)} paid)")

    # ------------------------------------------------------------------
    # 6. Amortization schedule
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("📅 Amortization Schedule")
    schedule_term = st.selectbox("Show schedule for term:", list(options.keys()), index=1)
    sched_data = options[schedule_term]
    schedule_df, _, _ = build_amortization_schedule(loan_amount, interest_rate, sched_data['months'], start_date)
    st.dataframe(schedule_df, use_container_width=True, height=280)
    st.download_button("📥 Download Amortization Schedule (CSV)",
                        schedule_df.to_csv(index=False).encode('utf-8'),
                        file_name=f"amortization_{schedule_term.lower()}.csv", mime="text/csv")

    # ------------------------------------------------------------------
    # 7. Recommendations
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("💡 Recommendations")
    score = recommended['affordability']['affordability_score']
    if score >= 80:
        st.success("✅ This loan is within your affordable range.")
    elif score >= 60:
        st.warning("⚠️ This loan is manageable but may strain your finances.")
    else:
        st.error("❌ This loan may be difficult to manage with your current financial situation.")

    recommendations = []
    if dti > 0.43:
        recommendations.append("Consider a longer term to reduce monthly payments")
    if burden > 0.8:
        recommendations.append("Look for ways to reduce monthly expenses")
    if savings < monthly_income * 0.1:
        recommendations.append("Build an emergency fund before taking the loan")
    if recommendations:
        st.markdown("**Suggested Actions:**")
        for rec in recommendations:
            st.markdown(f"- {rec}")

    # ------------------------------------------------------------------
    # 8. India-specific tips
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("🇮🇳 India-Specific Tips")
    with st.container(border=True):
        st.markdown("""
**Tax Benefits:**
- **Section 24(b):** Home loan interest deduction up to ₹2 L/year
- **Section 80C:** Principal repayment deduction up to ₹1.5 L/year
- **PMAY / CLSS:** First-time buyers may get an interest subsidy under Pradhan Mantri Awas Yojana

**Smart Repayment:**
- Even ₹5,000–₹10,000 extra per month as prepayment can cut your tenure by years
- Compare EAR (Effective Annual Rate), not just the headline rate, across banks
- SBI, HDFC, ICICI home loan rates typically range 8.5%–9.5% — negotiate!
""")

    # ------------------------------------------------------------------
    # 9. Save scenario / report
    # ------------------------------------------------------------------
    st.divider()
    save_col1, save_col2, save_col3 = st.columns([2, 1, 1])
    default_label = f"{format_amount(loan_amount, currency, compact=True)} @ {interest_rate:.1f}%"
    scenario_label = save_col1.text_input("Scenario label", value=default_label)

    pdf_bytes = build_report_pdf(scenario_label, cur_sym, loan_amount, interest_rate,
                                  monthly_income, monthly_expenses, options, risk_label, recommendations)
    save_col2.download_button("📥 Download Full Report (PDF)", pdf_bytes,
                               file_name="repayment_report.pdf", mime="application/pdf")

    if save_col3.button("💾 Save this scenario to my history"):
        if st.session_state.username:
            save_scenario(st.session_state.username, scenario_label, {
                'loan_amount': loan_amount, 'interest_rate': interest_rate,
                'monthly_income': monthly_income, 'monthly_expenses': monthly_expenses,
                'currency': currency, 'risk_label': risk_label,
            })
            st.success("Scenario saved.")
        else:
            st.info("Log in to save scenarios.")

    # ------------------------------------------------------------------
    # 10. Saved scenarios
    # ------------------------------------------------------------------
    st.subheader("📓 Your Saved Scenarios")
    if st.session_state.username:
        scenarios = get_saved_scenarios(st.session_state.username)
        if not scenarios:
            st.write("No saved scenarios yet — calculate a loan above and save it.")
        else:
            for s in scenarios:
                c1, c2 = st.columns([5, 1])
                p = s['params']
                c1.write(f"**{s['label']}** — {format_amount(p['loan_amount'], p['currency'], compact=True)} "
                         f"@ {p['interest_rate']}% · risk: {p['risk_label']} · saved {s['created_at']}")
                if c2.button("Delete", key=f"del_{s['id']}"):
                    delete_scenario(s['id'], st.session_state.username)
                    st.rerun()
    else:
        st.caption("Log in to view your saved scenario history.")

    # ------------------------------------------------------------------
    # 11. Prepayment simulator
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("💸 Prepayment Simulator")
    st.caption("See how much interest and time you save by paying extra toward your loan.")
    pp_col1, pp_col2, pp_col3 = st.columns(3)
    extra_monthly = pp_col1.number_input(f"Extra monthly payment ({cur_sym})", min_value=0, value=0, step=100)
    lump_sum = pp_col2.number_input(f"One-time lump sum ({cur_sym})", min_value=0, value=0, step=1000)
    lump_sum_month = pp_col3.number_input("Lump sum applied at month", min_value=1,
                                           max_value=recommended['months'], value=min(12, recommended['months']))

    if st.button("Simulate Prepayment"):
        sim = simulate_prepayment(loan_amount, interest_rate, recommended['months'], start_date,
                                   extra_monthly=extra_monthly, lump_sum=lump_sum, lump_sum_month=lump_sum_month)
        m1, m2 = st.columns(2)
        m1.metric("Loan Tenure", f"{sim['new_months']} months", f"-{sim['months_saved']} months")
        m2.metric("Total Interest", format_amount(sim['new_interest'], currency),
                  f"-{format_amount(sim['interest_saved'], currency, compact=True)}")

    # ------------------------------------------------------------------
    # 12. Compare multiple loan offers
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("⚖️ Compare Multiple Loan Offers")
    st.caption("Add 2 or more loan offers (e.g. from different banks) and compare total cost side by side.")

    if "offers" not in st.session_state:
        st.session_state.offers = [{
            "name": "Offer 1", "amount": loan_amount, "rate": interest_rate, "tenure": recommended['months'],
        }]

    for i, offer in enumerate(st.session_state.offers):
        oc1, oc2, oc3, oc4 = st.columns(4)
        offer["name"] = oc1.text_input("Offer name", value=offer["name"], key=f"offer_name_{i}")
        offer["amount"] = oc2.number_input(f"Amount ({cur_sym})", min_value=1000, value=int(offer["amount"]),
                                            step=1000, key=f"offer_amount_{i}")
        offer["rate"] = oc3.number_input("Interest Rate (%)", min_value=1.0, max_value=25.0,
                                          value=float(offer["rate"]), step=0.1, key=f"offer_rate_{i}")
        offer["tenure"] = oc4.number_input("Tenure (months)", min_value=6, max_value=480,
                                            value=int(offer["tenure"]), step=6, key=f"offer_tenure_{i}")

    if st.button("+ Add Offer"):
        st.session_state.offers.append({
            "name": f"Offer {len(st.session_state.offers) + 1}",
            "amount": loan_amount, "rate": interest_rate, "tenure": recommended['months'],
        })
        st.rerun()

    if st.button("Compare"):
        comp_rows = []
        for offer in st.session_state.offers:
            emi = calculate_monthly_payment(offer["amount"], offer["rate"], offer["tenure"])
            total_cost = emi * offer["tenure"]
            comp_rows.append({"Offer": offer["name"], "Monthly EMI": emi, "Total Cost": total_cost})
        comp_df = pd.DataFrame(comp_rows)
        fig_comp = px.bar(comp_df, x="Offer", y="Total Cost", template="plotly_dark",
                           color_discrete_sequence=[LIGHT_BLUE])
        st.plotly_chart(fig_comp, use_container_width=True)
        st.dataframe(comp_df, use_container_width=True)

    # ------------------------------------------------------------------
    # 13. AI-Powered Recommendations (Gemini)
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("🧠 AI-Powered Recommendations")
    st.caption("Get personalized repayment strategy suggestions from Gemini.")

    try:
        api_key = st.secrets.get("GEMINI_API_KEY")
    except Exception:
        api_key = None
    api_key = api_key or os.environ.get("GEMINI_API_KEY")

    if not api_key:
        st.warning("Set GEMINI_API_KEY in .streamlit/secrets.toml or as an environment variable "
                   "to enable AI recommendations.")
    else:
        if st.button("Get AI Recommendation"):
            with st.spinner("Thinking..."):
                try:
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel("gemini-2.5-flash")
                    prompt = f"""
A user has a loan of {loan_amount:,.0f} {currency} at {interest_rate:.1f}% annual interest,
with a monthly income of {monthly_income:,.0f} {currency} and monthly expenses of
{monthly_expenses:,.0f} {currency}. Their debt-to-income ratio for the recommended
tenure ({recommended['months']} months) is {dti * 100:.1f}%.

Write a structured markdown response with these sections, using headings:
1. "Initial Assessment & Loan Affordability" — briefly assess affordability and show
   the EMI for a 10, 15, and 20 year tenure as a short list.
2. "Recommended Repayment Strategies" — a numbered list with sub-bullets covering
   optimal tenure selection and aggressive prepayment strategies.
3. "Indian Tax Benefits" — explain Section 24(b) and Section 80C deductions relevant
   to this loan if it is a home loan.
4. "Conclusion" — a short closing paragraph.
Keep it concise and actionable.
"""
                    response = model.generate_content(prompt)
                    st.markdown(response.text)
                except Exception as e:
                    st.error(f"Error generating response: {e}")
