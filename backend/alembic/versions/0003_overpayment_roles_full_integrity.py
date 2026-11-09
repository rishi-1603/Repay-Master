"""Overpayment credit, operational roles, and full-balance integrity originals.

  * payments.credit_applied: money received beyond what was owed is kept for the customer
    (ledger account customer_credit) instead of being refused.
  * loan_accounts.interest_original / fees_original: the integrity check can now reconcile
    interest and fees the same way it already reconciled principal.
  * role_grants: operational roles (ops, admin) checked per request.

Backfill of the originals is exact, not a guess. Balances only move through successful
payments (and their reversals), so original = current balance + sum of applied amounts over
payments in state SUCCESSFUL. This also corrects principal_original for loans whose payments
were applied before 0002 ran, where 0002 had copied the already-reduced outstanding balance.
The downgrade drops the new columns and table and does not restore the 0002 values.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-09
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _applied_sum(column: str) -> str:
    return (f"(SELECT COALESCE(SUM(p.{column}), 0) FROM payments p "
            f"WHERE p.loan_id = loan_accounts.id AND p.state = 'SUCCESSFUL')")


def upgrade() -> None:
    op.create_table(
        "role_grants",
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("username", "role"),
    )

    with op.batch_alter_table("payments") as batch_op:
        batch_op.add_column(sa.Column("credit_applied", sa.BigInteger(), nullable=True, server_default="0"))
    op.execute("UPDATE payments SET credit_applied = 0 WHERE credit_applied IS NULL")
    with op.batch_alter_table("payments") as batch_op:
        batch_op.alter_column("credit_applied", existing_type=sa.BigInteger(), nullable=False,
                              server_default=None)

    with op.batch_alter_table("loan_accounts") as batch_op:
        batch_op.add_column(sa.Column("interest_original", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("fees_original", sa.BigInteger(), nullable=True))
    op.execute(f"UPDATE loan_accounts SET interest_original = interest_due + {_applied_sum('interest_applied')}")
    op.execute(f"UPDATE loan_accounts SET fees_original = fees_due + {_applied_sum('fee_applied')}")
    op.execute(f"UPDATE loan_accounts SET principal_original = principal_outstanding + "
               f"{_applied_sum('principal_applied')}")
    with op.batch_alter_table("loan_accounts") as batch_op:
        batch_op.alter_column("interest_original", existing_type=sa.BigInteger(), nullable=False)
        batch_op.alter_column("fees_original", existing_type=sa.BigInteger(), nullable=False)
        batch_op.create_check_constraint("ck_loan_interest_original_nonneg", "interest_original >= 0")
        batch_op.create_check_constraint("ck_loan_fees_original_nonneg", "fees_original >= 0")


def downgrade() -> None:
    with op.batch_alter_table("loan_accounts") as batch_op:
        batch_op.drop_constraint("ck_loan_fees_original_nonneg", type_="check")
        batch_op.drop_constraint("ck_loan_interest_original_nonneg", type_="check")
        batch_op.drop_column("fees_original")
        batch_op.drop_column("interest_original")
    with op.batch_alter_table("payments") as batch_op:
        batch_op.drop_column("credit_applied")
    op.drop_table("role_grants")
