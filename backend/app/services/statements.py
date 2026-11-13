"""Loan statements rebuilt from the journal.

Effect of an entry on what the customer owes: a repayment lowers it, a reversal
raises it back. Opening balance is the amount the loan was booked at. Interest
is not accrued in this module, so a statement shows postings only. It does
not show interest charges.

The closing balance from the journal must equal the cached loan balance. The
response reports that check as `reconciles_with_loan_balance`.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.db.models import JournalEntry, LoanAccount


@dataclass(frozen=True)
class StatementLine:
    posted_on: date
    kind: str
    amount: Decimal
    effect: Decimal  # signed change to the amount owed
    balance_after: Decimal


def _effect(entry: JournalEntry) -> Decimal:
    return -entry.amount if entry.kind == "repayment" else entry.amount


def build_statement(
    loan: LoanAccount, entries: list[JournalEntry], start: date | None, end: date | None
) -> dict:
    ordered = sorted(entries, key=lambda e: (e.posted_on, e.id))
    running = loan.opening_balance
    lines: list[StatementLine] = []
    opening_for_period = None

    for entry in ordered:
        before_period = start is not None and entry.posted_on < start
        after_period = end is not None and entry.posted_on > end
        if before_period:
            running += _effect(entry)
            continue
        if opening_for_period is None:
            opening_for_period = running
        if after_period:
            break
        running += _effect(entry)
        lines.append(StatementLine(entry.posted_on, entry.kind, entry.amount, _effect(entry), running))

    if opening_for_period is None:
        opening_for_period = running

    reconciles = None
    if end is None:
        reconciles = running == loan.balance

    return {
        "loan_id": loan.id,
        "period": {"from": start.isoformat() if start else None, "to": end.isoformat() if end else None},
        "opening_balance": f"{opening_for_period:.2f}",
        "closing_balance": f"{running:.2f}",
        "lines": [
            {
                "posted_on": line.posted_on.isoformat(),
                "kind": line.kind,
                "amount": f"{line.amount:.2f}",
                "effect": f"{line.effect:+.2f}",
                "balance_after": f"{line.balance_after:.2f}",
            }
            for line in lines
        ],
        "reconciles_with_loan_balance": reconciles,
    }
