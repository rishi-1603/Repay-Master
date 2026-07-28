from sqlalchemy.orm import Session
from app.modules.loans.models import Loan
from app.modules.loans.schemas import LoanCreate

def create_loan(db: Session, loan: LoanCreate, user_id: int, emi: float = None, risk: str = None):
    db_loan = Loan(**loan.model_dump(), owner_id=user_id, monthly_emi=emi, risk_category=risk)
    db.add(db_loan)
    db.commit()
    db.refresh(db_loan)
    return db_loan

def get_loans_by_user(db: Session, user_id: int):
    return db.query(Loan).filter(Loan.owner_id == user_id).all()
