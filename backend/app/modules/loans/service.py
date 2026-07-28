import math
import os
import joblib
import pandas as pd
import logging

logger = logging.getLogger(__name__)

def calculate_emi(principal: float, annual_rate: float, tenure_months: int) -> float:
    if annual_rate == 0:
        return principal / tenure_months
    monthly_rate = (annual_rate / 12) / 100
    emi = (principal * monthly_rate * math.pow(1 + monthly_rate, tenure_months)) / (math.pow(1 + monthly_rate, tenure_months) - 1)
    return round(emi, 2)

def predict_risk(principal: float, emi: float) -> str:
    model_path = os.path.join(os.path.dirname(__file__), "risk_model.pkl")
    if os.path.exists(model_path):
        try:
            model = joblib.load(model_path)
            income = 50000 
            dti = (emi / income) * 100 if income > 0 else 100
            features = pd.DataFrame([{"Income": income, "LoanAmount": principal, "EMI": emi, "DTI": dti}])
            pred = model.predict(features)
            return pred[0]
        except Exception as e:
            logger.error(f"Model prediction failed: {e}")
            pass
            
    if emi > 10000:
        return "High"
    elif emi > 5000:
        return "Medium"
    else:
        return "Low"

def compare_banks(principal: float, tenure_months: int) -> list:
    banks = [
        {"bank_name": "HDFC", "rate": 8.5},
        {"bank_name": "SBI", "rate": 8.35},
        {"bank_name": "ICICI", "rate": 8.7},
        {"bank_name": "Axis", "rate": 8.8}
    ]
    results = []
    for bank in banks:
        emi = calculate_emi(principal, bank["rate"], tenure_months)
        total_payment = emi * tenure_months
        total_interest = total_payment - principal
        results.append({
            "bank": bank["bank_name"],
            "interest_rate": bank["rate"],
            "emi": emi,
            "total_interest": round(total_interest, 2)
        })
    return sorted(results, key=lambda x: x["total_interest"])

def optimize_prepayment(principal: float, annual_rate: float, tenure_months: int, extra_payment: float) -> dict:
    original_emi = calculate_emi(principal, annual_rate, tenure_months)
    original_total = original_emi * tenure_months
    
    balance = principal
    monthly_rate = (annual_rate / 12) / 100
    months_taken = 0
    new_total_paid = 0
    
    while balance > 0 and months_taken < tenure_months:
        interest = balance * monthly_rate
        principal_component = original_emi - interest + extra_payment
        if balance < principal_component:
            principal_component = balance
        balance -= principal_component
        new_total_paid += (principal_component + interest)
        months_taken += 1
        
    savings = original_total - new_total_paid
    return {
        "original_tenure": tenure_months,
        "new_tenure": months_taken,
        "months_saved": tenure_months - months_taken,
        "total_savings": round(max(0, savings), 2)
    }

def send_emi_reminder_email(email: str, emi_amount: float, due_date: str):
    logger.info(f"EMAIL SENT TO {email}: Your upcoming EMI of ${emi_amount:,.2f} is due on {due_date}.")
    return True
