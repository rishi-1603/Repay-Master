"""Double-entry ledger rules. Pure functions: no database, no clock.

Chart of accounts (kept deliberately small):
  payment_clearing  asset      cash in transit from the payment provider
  loan_receivable   asset      principal the borrower still owes
  interest_income   revenue    interest earned
  fee_income        revenue    late and processing fees earned
  suspense          liability  unmatched receipts awaiting investigation

Every journal entry must balance: total debits == total credits, in integer paise.
Posted entries are never edited. A correction is a new reversing entry.
"""
from dataclasses import dataclass
from typing import Iterable

ACCOUNTS = {
    "payment_clearing": "asset",
    "loan_receivable": "asset",
    "interest_income": "revenue",
    "fee_income": "revenue",
    "suspense": "liability",
}
DEBIT, CREDIT = "D", "C"


class UnbalancedEntry(ValueError):
    pass


@dataclass(frozen=True)
class Line:
    account: str
    side: str     # "D" or "C"
    amount: int   # paise, strictly positive


def validate_entry(lines: list[Line]) -> None:
    if len(lines) < 2:
        raise UnbalancedEntry("a journal entry needs at least two lines")
    debits = credits = 0
    for line in lines:
        if line.account not in ACCOUNTS:
            raise UnbalancedEntry(f"unknown account {line.account!r}")
        if line.side not in (DEBIT, CREDIT):
            raise UnbalancedEntry(f"side must be D or C, got {line.side!r}")
        if not isinstance(line.amount, int) or line.amount <= 0:
            raise UnbalancedEntry("line amounts must be positive integers of paise")
        if line.side == DEBIT:
            debits += line.amount
        else:
            credits += line.amount
    if debits != credits:
        raise UnbalancedEntry(f"entry does not balance: debits {debits} != credits {credits}")


def repayment_lines(total: int, principal: int, interest: int, fee: int) -> list[Line]:
    """Lines for a successful repayment, allocated as principal + interest + fee."""
    if total != principal + interest + fee:
        raise UnbalancedEntry("allocation does not add up to the payment total")
    lines = [Line("payment_clearing", DEBIT, total)]
    for account, amount in (("loan_receivable", principal),
                            ("interest_income", interest),
                            ("fee_income", fee)):
        if amount > 0:
            lines.append(Line(account, CREDIT, amount))
    validate_entry(lines)
    return lines


def reversal_lines(lines: Iterable[Line]) -> list[Line]:
    """Mirror every line with its side flipped. Used for reversals, never for edits."""
    flipped = [Line(ln.account, CREDIT if ln.side == DEBIT else DEBIT, ln.amount) for ln in lines]
    validate_entry(flipped)
    return flipped


def signed_balance(account: str, lines: Iterable[Line]) -> int:
    """Natural-sign balance: assets and liabilities/revenue are shown positive when normal."""
    debit_total = sum(ln.amount for ln in lines if ln.account == account and ln.side == DEBIT)
    credit_total = sum(ln.amount for ln in lines if ln.account == account and ln.side == CREDIT)
    return debit_total - credit_total if ACCOUNTS[account] == "asset" else credit_total - debit_total


def trial_balance_is_zero(lines: Iterable[Line]) -> bool:
    """Across the whole ledger, total debits must equal total credits."""
    net = 0
    for ln in lines:
        net += ln.amount if ln.side == DEBIT else -ln.amount
    return net == 0
