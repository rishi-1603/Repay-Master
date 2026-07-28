from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.core.dependencies import get_db, get_current_user
from app.modules.users.models import User
from app.modules.loans import crud as loan_crud
from app.modules.reports.service import generate_loan_pdf

router = APIRouter()

@router.get("/pdf/{loan_id}")
def download_loan_pdf(
    loan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    loan = db.query(loan_crud.Loan).filter(loan_crud.Loan.id == loan_id, loan_crud.Loan.owner_id == current_user.id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")
        
    pdf_path = generate_loan_pdf(loan, current_user.full_name or current_user.email)
    
    return FileResponse(
        pdf_path,
        media_type='application/pdf',
        filename=f"RepayMaster_Report_{loan.title}.pdf"
    )
