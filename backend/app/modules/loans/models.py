from sqlalchemy import Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import relationship
from app.db.database import Base

class Loan(Base):
    __tablename__ = "loans"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    principal = Column(Float)
    annual_interest_rate = Column(Float)
    tenure_months = Column(Integer)
    monthly_emi = Column(Float, nullable=True)
    risk_category = Column(String, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"))

    owner = relationship("User", back_populates="loans")
