"""Loan accounts and their append-only journal.

The journal is the source of truth for statements. `loan_accounts.balance` is a
cached figure that the ledger service keeps in step with the journal inside the
same transaction; the statement endpoint checks that they agree.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

MONEY = Numeric(14, 2)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LoanAccount(Base):
    __tablename__ = "loan_accounts"
    __table_args__ = (CheckConstraint("balance >= 0", name="ck_loan_balance_non_negative"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    opening_balance: Mapped[Decimal] = mapped_column(MONEY)
    balance: Mapped[Decimal] = mapped_column(MONEY)
    # None means the loan has no schedule yet; it is reported as "unscheduled", never as current.
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    opened_on: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    entries: Mapped[list["JournalEntry"]] = relationship(
        back_populates="loan", order_by="JournalEntry.id", cascade="all, delete-orphan"
    )


class JournalEntry(Base):
    __tablename__ = "loan_journal"
    __table_args__ = (
        CheckConstraint("kind IN ('repayment', 'reversal')", name="ck_journal_kind"),
        CheckConstraint("amount > 0", name="ck_journal_amount_positive"),
        Index("ix_loan_journal_loan_posted", "loan_id", "posted_on"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("loan_accounts.id", ondelete="CASCADE"))
    posted_on: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    # For a reversal: the repayment it undoes. Unique, so one repayment is reversed at most once.
    reverses_id: Mapped[int | None] = mapped_column(
        ForeignKey("loan_journal.id"), unique=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    loan: Mapped[LoanAccount] = relationship(back_populates="entries")
