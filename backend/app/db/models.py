"""Persistence model. Amounts are integer paise (BigInteger), never floats.

Invariants enforced by the database, not only by application code:
  * journal_entries.idempotency_key is unique: an entry can be posted only once.
  * journal_lines.amount is strictly positive, and side is D or C.
  * payments(loan_id, idempotency_key) is unique: a retried intent cannot double-create.
  * payments.provider_reference is unique: one provider transaction maps to one payment.
  * webhook_events.event_id is unique: a redelivered webhook is recognised and ignored.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LoanAccount(Base):
    __tablename__ = "loan_accounts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    principal_outstanding: Mapped[int] = mapped_column(BigInteger, CheckConstraint("principal_outstanding >= 0"))
    interest_due: Mapped[int] = mapped_column(BigInteger, CheckConstraint("interest_due >= 0"))
    fees_due: Mapped[int] = mapped_column(BigInteger, CheckConstraint("fees_due >= 0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    payments: Mapped[list["Payment"]] = relationship(back_populates="loan")


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("loan_id", "idempotency_key", name="uq_payment_intent"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    loan_id: Mapped[str] = mapped_column(ForeignKey("loan_accounts.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    reference: Mapped[str] = mapped_column(String(64), unique=True)
    provider_reference: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    amount: Mapped[int] = mapped_column(BigInteger, CheckConstraint("amount > 0"))
    state: Mapped[str] = mapped_column(String(16), index=True)
    fee_applied: Mapped[int] = mapped_column(BigInteger, default=0)
    interest_applied: Mapped[int] = mapped_column(BigInteger, default=0)
    principal_applied: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    loan: Mapped[LoanAccount] = relationship(back_populates="payments")


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), unique=True)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[str] = mapped_column(Text)
    result: Mapped[str] = mapped_column(String(32))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str] = mapped_column(String(255))
    reverses_entry_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entries.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    lines: Mapped[list["JournalLine"]] = relationship(back_populates="entry", order_by="JournalLine.id")


class JournalLine(Base):
    __tablename__ = "journal_lines"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_line_positive"),
        CheckConstraint("side IN ('D', 'C')", name="ck_line_side"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entries.id"), index=True)
    account: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(1))
    amount: Mapped[int] = mapped_column(BigInteger)

    entry: Mapped[JournalEntry] = relationship(back_populates="lines")
