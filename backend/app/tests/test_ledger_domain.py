"""Pure-domain tests: double-entry rules, money, payment state machine, signatures."""
import pytest

from app.domain.ledger import (
    DEBIT,
    Line,
    UnbalancedEntry,
    repayment_lines,
    reversal_lines,
    signed_balance,
    trial_balance_is_zero,
    validate_entry,
)
from app.domain.money import to_major_str, to_minor
from app.domain.payments import (
    InvalidTransition,
    PaymentState,
    allocate,
    sign_payload,
    transition,
    verify_signature,
)
from app.domain.reconciliation import reconcile


def test_repayment_entry_balances_and_moves_receivable():
    lines = repayment_lines(total=500000, principal=300000, interest=150000, fee=50000)
    assert trial_balance_is_zero(lines)
    assert signed_balance("payment_clearing", lines) == 500000
    assert signed_balance("loan_receivable", lines) == -300000
    assert signed_balance("interest_income", lines) == 150000


def test_unbalanced_entry_is_rejected():
    with pytest.raises(UnbalancedEntry, match="does not balance"):
        validate_entry([Line("payment_clearing", DEBIT, 100), Line("loan_receivable", "C", 99)])


@pytest.mark.parametrize("bad", [
    [Line("payment_clearing", DEBIT, 100)],                                  # one line
    [Line("nope", DEBIT, 100), Line("suspense", "C", 100)],                 # unknown account
    [Line("payment_clearing", "X", 100), Line("suspense", "C", 100)],       # bad side
    [Line("payment_clearing", DEBIT, 0), Line("suspense", "C", 0)],         # zero amount
])
def test_malformed_entries_are_rejected(bad):
    with pytest.raises(UnbalancedEntry):
        validate_entry(bad)


def test_reversal_mirrors_and_nets_to_zero():
    original = repayment_lines(500000, 300000, 150000, 50000)
    reversal = reversal_lines(original)
    combined = original + reversal
    assert trial_balance_is_zero(combined)
    assert signed_balance("payment_clearing", combined) == 0
    assert signed_balance("loan_receivable", combined) == 0


def test_repayment_allocation_must_add_up():
    with pytest.raises(UnbalancedEntry):
        repayment_lines(total=100, principal=50, interest=10, fee=0)


def test_waterfall_pays_fees_then_interest_then_principal():
    assert allocate(100000, fees_due=50000, interest_due=30000, principal_outstanding=500000) == (50000, 30000, 20000, 0)
    assert allocate(20000, fees_due=50000, interest_due=30000, principal_outstanding=500000) == (20000, 0, 0, 0)


def test_overpayment_is_applied_up_to_the_amount_owed_and_the_excess_is_credit():
    # owed 100 (fee 10, interest 20, principal 70); paying 130 clears the loan and credits 30
    assert allocate(13000, fees_due=1000, interest_due=2000, principal_outstanding=7000) == (1000, 2000, 7000, 3000)


def test_repayment_with_overpayment_credit_posts_to_customer_credit_and_balances():
    lines = repayment_lines(total=13000, principal=7000, interest=2000, fee=1000, credit=3000)
    assert trial_balance_is_zero(lines)
    assert signed_balance("customer_credit", lines) == 3000
    with pytest.raises(UnbalancedEntry):
        repayment_lines(total=13000, principal=7000, interest=2000, fee=1000, credit=2000)


def test_payment_state_machine_allows_only_defined_moves():
    assert transition(PaymentState.INITIATED, PaymentState.PENDING) is PaymentState.PENDING
    assert transition(PaymentState.FAILED, PaymentState.PENDING) is PaymentState.PENDING
    assert transition(PaymentState.SUCCESSFUL, PaymentState.REVERSED) is PaymentState.REVERSED
    for current, target in [(PaymentState.FAILED, PaymentState.SUCCESSFUL),
                            (PaymentState.INITIATED, PaymentState.SUCCESSFUL),
                            (PaymentState.REVERSED, PaymentState.PENDING),
                            (PaymentState.SUCCESSFUL, PaymentState.FAILED)]:
        with pytest.raises(InvalidTransition):
            transition(current, target)


def test_signature_accepts_valid_and_rejects_tampered_wrong_key_and_stale():
    body, now = b'{"id":"evt_1"}', 1_800_000_000
    header = sign_payload("secret-key", body, now)
    assert verify_signature("secret-key", body, header, now)
    assert not verify_signature("secret-key", b'{"id":"evt_2"}', header, now)   # tampered body
    assert not verify_signature("other-key", body, header, now)                 # wrong key
    assert not verify_signature("secret-key", body, header, now + 301)          # replay window
    assert not verify_signature("secret-key", body, None, now)                  # no header
    assert not verify_signature("", body, header, now)                          # no secret configured


def test_money_is_exact_and_rejects_sub_paisa():
    assert to_minor("1234.56") == 123456
    assert to_minor(0.3) == 30
    with pytest.raises(ValueError):          # float noise (0.1+0.2) is refused, not rounded
        to_minor(0.1 + 0.2)
    assert to_major_str(123456) == "1234.56"
    assert to_major_str(5) == "0.05"
    with pytest.raises(ValueError):
        to_minor("10.001")
    with pytest.raises(ValueError):
        to_minor("nan")


def test_reconciliation_detects_each_exception_type():
    internal = [
        {"reference": "A", "amount": 100, "state": "SUCCESSFUL"},          # missing from settlement
        {"reference": "B", "amount": 200, "state": "PENDING"},             # provider settled, we did not post
        {"reference": "C", "amount": 300, "state": "SUCCESSFUL"},          # amount differs
        {"reference": "D", "amount": 400, "state": "REVERSED"},            # still settled at provider
        {"reference": "E", "amount": 500, "state": "SUCCESSFUL"},          # provider refunded, we did not reverse
        {"reference": "F", "amount": 600, "state": "SUCCESSFUL"},          # settled twice
    ]
    settlement = [
        {"reference": "B", "amount": 200, "status": "settled"},
        {"reference": "C", "amount": 999, "status": "settled"},
        {"reference": "D", "amount": 400, "status": "settled"},
        {"reference": "E", "amount": 500, "status": "refunded"},
        {"reference": "F", "amount": 600, "status": "settled"},
        {"reference": "F", "amount": 600, "status": "settled"},
        {"reference": "Z", "amount": 700, "status": "settled"},           # unknown to us
    ]
    kinds = {(e["type"], e["reference"]) for e in reconcile(internal, settlement)}
    assert kinds == {
        ("MISSING_SETTLEMENT", "A"), ("NOT_POSTED_INTERNALLY", "B"), ("AMOUNT_MISMATCH", "C"),
        ("REVERSAL_NOT_REFLECTED", "D"), ("REVERSAL_NOT_REFLECTED", "E"),
        ("DUPLICATE_SETTLEMENT", "F"), ("UNKNOWN_IN_INTERNAL", "Z"),
    }


def test_clean_reconciliation_has_no_exceptions():
    internal = [{"reference": "A", "amount": 100, "state": "SUCCESSFUL"}]
    assert reconcile(internal, [{"reference": "A", "amount": 100, "status": "settled"}]) == []
