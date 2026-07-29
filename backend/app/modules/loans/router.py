from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.core.dependencies import get_db, get_current_user
from app.modules.users.models import User
from app.modules.loans import crud, schemas, service

router = APIRouter()

@router.post("/", response_model=schemas.LoanResponse)
def create_loan_for_user(
    loan_in: schemas.LoanCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    emi = service.calculate_emi(loan_in.principal, loan_in.annual_interest_rate, loan_in.tenure_months)
    risk_data = service.predict_risk(loan_in.principal, emi, loan_in.monthly_income)
    
    db_loan = crud.create_loan(db=db, loan=loan_in, user_id=current_user.id, emi=emi, risk=risk_data["label"])
    
    due_date = (datetime.utcnow() + timedelta(days=30)).strftime("%Y-%m-%d")
    service.send_emi_reminder_email(current_user.email, emi, due_date)
    
    return db_loan

@router.get("/{loan_id}/analytics")
def get_loan_analytics(loan_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    loan = db.query(crud.Loan).filter(crud.Loan.id == loan_id, crud.Loan.owner_id == current_user.id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")
    return service.get_analytics(loan.principal, loan.annual_interest_rate, loan.tenure_months, loan.monthly_income, loan.monthly_expenses)

@router.get("/compare")
def compare_loan_banks(principal: float, tenure_months: int, current_user: User = Depends(get_current_user)):
    return service.compare_banks(principal, tenure_months)

@router.post("/optimize")
def optimize_loan_prepayment(principal: float, annual_interest_rate: float, tenure_months: int, extra_payment: float, current_user: User = Depends(get_current_user)):
    return service.optimize_prepayment(principal, annual_interest_rate, tenure_months, extra_payment)

@router.get("/", response_model=List[schemas.LoanResponse])
def read_loans(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return crud.get_loans_by_user(db=db, user_id=current_user.id)
