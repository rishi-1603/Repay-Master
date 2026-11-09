"""Compare the internal ledger's view of payments with a provider settlement report.

Pure function: takes two lists and returns exceptions. Amounts are integer paise.
Exception types:
  MISSING_SETTLEMENT          internally SUCCESSFUL but absent from the settlement report
  NOT_POSTED_INTERNALLY       the provider settled it but we do not hold it as SUCCESSFUL
  UNKNOWN_IN_INTERNAL         settled by the provider with no matching internal payment
  AMOUNT_MISMATCH             both sides have it, amounts differ
  DUPLICATE_SETTLEMENT        the settlement report lists the same reference twice
  REVERSAL_NOT_REFLECTED      one side shows a reversal or refund, the other does not
"""


def reconcile(internal: list[dict], settlement: list[dict]) -> list[dict]:
    exceptions: list[dict] = []
    by_ref_settle: dict[str, list[dict]] = {}
    for row in settlement:
        by_ref_settle.setdefault(row["reference"], []).append(row)
    internal_by_ref = {p["reference"]: p for p in internal}

    for ref, rows in by_ref_settle.items():
        if len(rows) > 1:
            exceptions.append({"type": "DUPLICATE_SETTLEMENT", "reference": ref,
                               "detail": f"{len(rows)} settlement rows"})

    for ref, rows in by_ref_settle.items():
        row = rows[0]
        payment = internal_by_ref.get(ref)
        if payment is None:
            exceptions.append({"type": "UNKNOWN_IN_INTERNAL", "reference": ref,
                               "detail": "settled by provider, no internal payment"})
            continue
        if row["status"] == "settled":
            if payment["state"] == "REVERSED":
                exceptions.append({"type": "REVERSAL_NOT_REFLECTED", "reference": ref,
                                   "detail": "internally reversed, still settled at provider"})
            elif payment["state"] != "SUCCESSFUL":
                exceptions.append({"type": "NOT_POSTED_INTERNALLY", "reference": ref,
                                   "detail": f"provider settled, internal state {payment['state']}"})
            elif payment["amount"] != row["amount"]:
                exceptions.append({"type": "AMOUNT_MISMATCH", "reference": ref,
                                   "detail": f"internal {payment['amount']} vs settled {row['amount']}"})
        elif row["status"] == "refunded":
            if payment["state"] != "REVERSED":
                exceptions.append({"type": "REVERSAL_NOT_REFLECTED", "reference": ref,
                                   "detail": f"provider refunded, internal state {payment['state']}"})

    for payment in internal:
        if payment["state"] == "SUCCESSFUL" and payment["reference"] not in by_ref_settle:
            exceptions.append({"type": "MISSING_SETTLEMENT", "reference": payment["reference"],
                               "detail": "internally successful, absent from settlement"})
    return exceptions
