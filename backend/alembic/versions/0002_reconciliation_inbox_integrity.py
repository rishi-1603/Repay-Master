"""Reconciliation runs, webhook inbox with retry state, loan principal_original.

Existing rows are backfilled, so this migration is safe on a database that already
holds data. principal_original is backfilled from principal_outstanding: the true
original is unknown for loans created before this migration. Any loan whose principal
was already reduced by payments needs manual correction before integrity checks mean
anything for it.

Revision ID: 0002
Revises: 355258b2f058
Create Date: 2026-11-09
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "355258b2f058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reconciliation_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_by", sa.String(length=64), nullable=False),
        sa.Column("checked_internal", sa.Integer(), nullable=False),
        sa.Column("checked_settlement", sa.Integer(), nullable=False),
        sa.Column("exception_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "reconciliation_exceptions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("reference", sa.String(length=64), nullable=False),
        sa.Column("detail", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["reconciliation_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reconciliation_exceptions_run_id", "reconciliation_exceptions", ["run_id"])

    # loan_accounts: add nullable, backfill, then enforce NOT NULL.
    op.add_column("loan_accounts", sa.Column("principal_original", sa.BigInteger(), nullable=True))
    op.execute("UPDATE loan_accounts SET principal_original = principal_outstanding")
    with op.batch_alter_table("loan_accounts") as batch_op:
        batch_op.alter_column("principal_original", existing_type=sa.BigInteger(), nullable=False)
        batch_op.create_check_constraint("ck_loan_principal_original_positive", "principal_original > 0")

    # webhook_events: the existing 'result' column becomes nullable (set when processed).
    with op.batch_alter_table("webhook_events") as batch_op:
        batch_op.alter_column("result", existing_type=sa.String(length=32), nullable=True)
        batch_op.add_column(sa.Column("status", sa.String(length=16), nullable=True, server_default="PROCESSED"))
        batch_op.add_column(sa.Column("attempts", sa.Integer(), nullable=True, server_default="0"))
        batch_op.add_column(sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("last_error", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True))
    # Rows written before this migration were already processed synchronously.
    op.execute("UPDATE webhook_events SET next_attempt_at = received_at, processed_at = received_at")
    with op.batch_alter_table("webhook_events") as batch_op:
        batch_op.alter_column("status", existing_type=sa.String(length=16), nullable=False, server_default=None)
        batch_op.alter_column("attempts", existing_type=sa.Integer(), nullable=False, server_default=None)
        batch_op.alter_column("next_attempt_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch_op.create_index("ix_webhook_events_status", ["status"])


def downgrade() -> None:
    with op.batch_alter_table("webhook_events") as batch_op:
        batch_op.drop_index("ix_webhook_events_status")
        batch_op.drop_column("processed_at")
        batch_op.drop_column("last_error")
        batch_op.drop_column("next_attempt_at")
        batch_op.drop_column("attempts")
        batch_op.drop_column("status")
        batch_op.alter_column("result", existing_type=sa.String(length=32), nullable=False)
    with op.batch_alter_table("loan_accounts") as batch_op:
        batch_op.drop_constraint("ck_loan_principal_original_positive", type_="check")
        batch_op.drop_column("principal_original")
    op.drop_index("ix_reconciliation_exceptions_run_id", table_name="reconciliation_exceptions")
    op.drop_table("reconciliation_exceptions")
    op.drop_table("reconciliation_runs")
