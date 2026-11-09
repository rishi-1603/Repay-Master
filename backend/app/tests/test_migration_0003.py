"""Migration 0003 on a database that already has loans and payments.

Runs the real Alembic revisions against a temporary SQLite file: the history is written at
revision 0002 (the state a production database would be in), then 0003 is applied and the
backfilled originals are checked against the balances the history implies.
"""
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.core.config import settings
from app.db.base import get_engine

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture()
def migrations(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    yield cfg, url
    get_engine.cache_clear()


def _insert_legacy_history(url: str) -> None:
    engine = create_engine(url)
    now = "2026-10-01 10:00:00"
    with engine.begin() as c:
        # Loan 1: 100 principal, 2 interest, 0 fees. Payment of 40 (3 interest, 40 principal) succeeded,
        # then a second payment of 10 was reversed. Balances: principal 60, interest 2 - 3 is impossible,
        # so the history below is built to be consistent: interest 5 originally, 3 paid, 2 left.
        c.execute(text("INSERT INTO loan_accounts (id, owner, principal_original, principal_outstanding, "
                       "interest_due, fees_due, created_at) VALUES "
                       "('LN-MIG', 'alice', 100, 60, 2, 0, :now)"), {"now": now})
        for key, ref, state, interest, principal in [
            ("mig-key-0001", "PAY-MIG-1", "SUCCESSFUL", 3, 40),
            ("mig-key-0002", "PAY-MIG-2", "REVERSED", 0, 10),
        ]:
            c.execute(text("INSERT INTO payments (loan_id, idempotency_key, reference, amount, state, fee_applied, "
                           "interest_applied, principal_applied, created_at, updated_at) VALUES "
                           "('LN-MIG', :key, :ref, :amount, :state, 0, :interest, :principal, :now, :now)"),
                      {"key": key, "ref": ref, "amount": interest + principal, "state": state,
                       "interest": interest, "principal": principal, "now": now})
        # Loan 2 has no payments: its originals are simply its current balances.
        c.execute(text("INSERT INTO loan_accounts (id, owner, principal_original, principal_outstanding, "
                       "interest_due, fees_due, created_at) VALUES "
                       "('LN-NEW', 'bob', 500, 500, 7, 1, :now)"), {"now": now})
    engine.dispose()


def test_0003_backfills_exact_originals_from_payment_history(migrations):
    cfg, url = migrations
    command.upgrade(cfg, "0002")
    _insert_legacy_history(url)
    command.upgrade(cfg, "head")

    engine = create_engine(url)
    with engine.connect() as c:
        rows = {r.id: r for r in c.execute(text(
            "SELECT id, principal_original, interest_original, fees_original, principal_outstanding, "
            "interest_due, fees_due FROM loan_accounts")).all()}
        credit_defaults = c.execute(text("SELECT DISTINCT credit_applied FROM payments")).scalars().all()
    engine.dispose()

    mig = rows["LN-MIG"]
    assert mig.principal_original == 100          # 60 outstanding + 40 applied by the SUCCESSFUL payment
    assert mig.interest_original == 5             # 2 due + 3 applied
    assert mig.fees_original == 0
    assert credit_defaults == [0]                 # existing payments carry no overpayment credit

    new = rows["LN-NEW"]
    assert (new.principal_original, new.interest_original, new.fees_original) == (500, 7, 1)


def test_0003_creates_role_grants_and_downgrades_cleanly(migrations):
    cfg, url = migrations
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    assert "role_grants" in inspect(engine).get_table_names()
    engine.dispose()
    command.downgrade(cfg, "0002")
    engine = create_engine(url)
    tables = inspect(engine).get_table_names()
    columns = {c["name"] for c in inspect(engine).get_columns("loan_accounts")}
    engine.dispose()
    assert "role_grants" not in tables
    assert "interest_original" not in columns and "principal_original" in columns
