"""Simple one-page PDF summary report using fpdf2 (pure-Python, no system deps)."""
from fpdf import FPDF


def _latin1(text) -> str:
    """Make text safe for fpdf2's built-in latin-1 core fonts.

    ₹ becomes "Rs. " (readable in INR reports); any other character outside
    latin-1 (e.g. emoji or € from a user-typed scenario label) becomes "?"
    instead of raising FPDFUnicodeEncodingException. (D4-2b)
    """
    return str(text).replace("₹", "Rs. ").encode("latin-1", "replace").decode("latin-1")


def build_report_pdf(scenario_label, currency_symbol, loan_amount, interest_rate,
                      monthly_income, monthly_expenses, options: dict, risk_label,
                      recommendations: list) -> bytes:
    # fpdf2's built-in core fonts (helvetica) only support latin-1, so the ₹
    # glyph can't be rendered directly -- fall back to "Rs." in the PDF only.
    if currency_symbol == "₹":
        currency_symbol = "Rs. "
    currency_symbol = _latin1(currency_symbol)
    scenario_label = _latin1(scenario_label)

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "RepayMaster - Loan Repayment Report", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, f"Scenario: {scenario_label}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Loan & Financial Inputs", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Loan Amount: {currency_symbol}{loan_amount:,.0f}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Interest Rate: {interest_rate:.2f}%", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Monthly Income: {currency_symbol}{monthly_income:,.0f}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Monthly Expenses: {currency_symbol}{monthly_expenses:,.0f}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Repayment Options", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    for term_name, data in options.items():
        pdf.cell(0, 6,
                 f"{term_name}: {data['months']} months, "
                 f"EMI {currency_symbol}{data['monthly_payment']:,.2f}, "
                 f"Total Interest {currency_symbol}{data['total_interest']:,.2f}",
                 new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, f"Predicted Risk Level: {risk_label}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    if recommendations:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Recommendations", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        for rec in recommendations:
            # new_x/new_y: without them the cursor stays at the right margin and the
            # next call has no width left to render into. (D4-2a)
            pdf.multi_cell(0, 6, _latin1(f"- {rec}"), new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())
