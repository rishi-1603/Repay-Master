from pydantic import BaseModel
from typing import Optional

class LoanBase(BaseModel):
    title: str
    principal: float
    annual_interest_rate: float
    tenure_months: int

class LoanCreate(LoanBase):
    pass

class LoanResponse(LoanBase):
    id: int
    monthly_emi: Optional[float] = None
    risk_category: Optional[str] = None
    owner_id: int
    class Config:
        from_attributes = True
