"""Payment lifecycle, waterfall allocation, and webhook signature verification.

Payment state machine:
    INITIATED -> PENDING -> SUCCESSFUL -> REVERSED
                    |  ^
                    v  |
                  FAILED   (a failed payment can be retried: FAILED -> PENDING)
"""
import hashlib
import hmac
from enum import Enum


class PaymentState(str, Enum):
    INITIATED = "INITIATED"
    PENDING = "PENDING"
    SUCCESSFUL = "SUCCESSFUL"
    FAILED = "FAILED"
    REVERSED = "REVERSED"


ALLOWED_TRANSITIONS = {
    PaymentState.INITIATED: {PaymentState.PENDING},
    PaymentState.PENDING: {PaymentState.SUCCESSFUL, PaymentState.FAILED},
    PaymentState.FAILED: {PaymentState.PENDING},
    PaymentState.SUCCESSFUL: {PaymentState.REVERSED},
    PaymentState.REVERSED: set(),
}


class InvalidTransition(ValueError):
    pass


def transition(current: PaymentState, target: PaymentState) -> PaymentState:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransition(f"cannot move a payment from {current.value} to {target.value}")
    return target


def allocate(amount: int, fees_due: int, interest_due: int, principal_outstanding: int):
    """Waterfall: fees first, then interest, then principal. Amounts in paise.

    Returns (fee, interest, principal, credit). Whatever exceeds the amount owed is
    `credit`: it is kept for the customer (a liability), not refused and not dropped.
    """
    if amount <= 0:
        raise ValueError("payment amount must be positive")
    owed = fees_due + interest_due + principal_outstanding
    applicable = min(amount, owed)
    fee = min(applicable, fees_due)
    interest = min(applicable - fee, interest_due)
    principal = applicable - fee - interest
    return fee, interest, principal, amount - applicable


SIGNATURE_TOLERANCE_SECONDS = 300


def sign_payload(secret: str, body: bytes, timestamp: int) -> str:
    """Header value for a payload: 't=<unix>,v1=<hex hmac-sha256 of "<t>.<body>">'."""
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={mac}"


def verify_signature(secret: str, body: bytes, header: str | None, now: int,
                     tolerance: int = SIGNATURE_TOLERANCE_SECONDS) -> bool:
    """Constant-time HMAC check plus a replay window on the signed timestamp."""
    if not secret or not header:
        return False
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    try:
        timestamp = int(parts["t"])
    except (KeyError, ValueError):
        return False
    if abs(now - timestamp) > tolerance:
        return False
    expected = sign_payload(secret, body, timestamp).split("v1=", 1)[1]
    return hmac.compare_digest(expected, parts.get("v1", ""))
