"""Money as integer minor units (paise). Never float, never a SQL decimal column.

Amounts enter the system as Decimal/str with at most two decimal places, are stored
and computed as integers in paise, and leave as two-decimal strings.
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MINOR_PER_MAJOR = 100
_CENT = Decimal("0.01")


def to_minor(value) -> int:
    """Convert a decimal-like value to paise. Rejects values finer than one paisa."""
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"not a money amount: {value!r}") from exc
    if not d.is_finite():
        raise ValueError("money amount must be finite")
    if d != d.quantize(_CENT, rounding=ROUND_HALF_UP):
        raise ValueError("money amount has more than two decimal places")
    return int(d * MINOR_PER_MAJOR)


def to_major_str(minor: int) -> str:
    """Render paise as a two-decimal string, e.g. 1234567 -> '12345.67'."""
    sign = "-" if minor < 0 else ""
    whole, frac = divmod(abs(minor), MINOR_PER_MAJOR)
    return f"{sign}{whole}.{frac:02d}"
