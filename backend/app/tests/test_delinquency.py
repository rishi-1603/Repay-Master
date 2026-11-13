"""Arrears bucket rules. Pure functions, so no database is needed."""
from datetime import date
from decimal import Decimal

import pytest

from app.services.delinquency import bucket_for, days_past_due

AS_OF = date(2026, 9, 1)


@pytest.mark.parametrize(
    "days_late, expected",
    [
        (0, "current"),       # due today is not yet late
        (1, "1-30"),
        (30, "1-30"),
        (31, "31-60"),
        (60, "31-60"),
        (61, "61-90"),
        (90, "61-90"),
        (91, "90+"),
        (400, "90+"),
    ],
)
def test_bucket_boundaries(days_late, expected):
    due = date.fromordinal(AS_OF.toordinal() - days_late)
    assert bucket_for(Decimal("500.00"), due, AS_OF) == expected


def test_future_due_date_is_current():
    assert bucket_for(Decimal("500.00"), date(2026, 9, 10), AS_OF) == "current"
    assert days_past_due(date(2026, 9, 10), AS_OF) == 0


def test_zero_balance_is_closed_whatever_the_due_date():
    assert bucket_for(Decimal("0.00"), date(2020, 1, 1), AS_OF) == "closed"


def test_no_due_date_is_unscheduled_never_current():
    assert bucket_for(Decimal("500.00"), None, AS_OF) == "unscheduled"
    assert days_past_due(None, AS_OF) == 0
