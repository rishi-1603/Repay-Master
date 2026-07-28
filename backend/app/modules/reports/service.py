from fpdf import FPDF
from app.modules.loans.models import Loan
import tempfile
import os

def generate_loan_pdf(loan: Loan, user_name: str) -> str:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    
    pdf.cell(200, 10, txt="RepayMaster AI - Loan Report", ln=True, align='C')
    pdf.ln(10)
    
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Prepared for: {user_name}", ln=True)
    pdf.cell(200, 10, txt=f"Loan Title: {loan.title}", ln=True)
    pdf.cell(200, 10, txt=f"Principal Amount: ${loan.principal:,.2f}", ln=True)
    pdf.cell(200, 10, txt=f"Annual Interest Rate: {loan.annual_interest_rate}%", ln=True)
    pdf.cell(200, 10, txt=f"Tenure: {loan.tenure_months} months", ln=True)
    pdf.cell(200, 10, txt=f"Monthly EMI: ${loan.monthly_emi:,.2f}", ln=True)
    pdf.cell(200, 10, txt=f"Risk Category: {loan.risk_category}", ln=True)
    
    pdf.ln(10)
    pdf.set_font("Arial", 'I', 10)
    pdf.cell(200, 10, txt="Generated automatically by RepayMaster AI Enterprise Platform.", ln=True)
    
    temp_fd, temp_path = tempfile.mkstemp(suffix=".pdf")
    os.close(temp_fd)
    pdf.output(temp_path)
    
    return temp_path
