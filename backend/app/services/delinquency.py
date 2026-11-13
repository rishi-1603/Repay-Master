"""Arrears aging. Pure functions, so the bucket rules can be tested without a database.

days past due = as_of - due_date, counted only once the due date has passed.
Buckets: current (not yet due), 1-30, 31-60, 61-90, 90+.
A loan with no balance is "closed". A loan with a balance and no due date is
"unscheduled", never current, because nothing says it is being paid.
"""
from datetime import date
from decimal import Decimal

BUCKETS = ("current", "1-30", "31-60", "61-90", "90+", "unscheduled", "closed")
ARREARS_BUCKETS = ("1-30", "31-60", "61-90", "90+")


def days_past_due(due: date | None, as_of: date) -> int:
    if due is None:
        return 0
    return max((as_of - due).days, 0)


def bucket_for(balance: Decimal, due: date | None, as_of: date) -> str:
    if balance <= 0:
        return "closed"
    if due is None:
        return "unscheduled"
    days = days_past_due(due, as_of)
    if days == 0:
        return "current"
    if days <= 30:
        return "1-30"
    if days <= 60:
        return "31-60"
    if days <= 90:
        return "61-90"
    return "90+"
