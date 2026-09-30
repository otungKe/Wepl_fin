"""Money helpers shared by every module.

Amounts are ``Decimal`` in the currency's minor unit precision (two places for
KES), never floats. Rounding only happens in ``allocate``, which splits an
amount exactly: the parts always add back to the whole.
"""
from decimal import ROUND_DOWN, Decimal

CURRENCY = "KES"
CENT = Decimal("0.01")


def to_money(value) -> Decimal:
    """Parse a money amount, rejecting anything with more than two decimals."""
    if isinstance(value, float):
        raise TypeError("Money must not be a float; pass a string or Decimal.")
    amount = Decimal(str(value))
    if amount != amount.quantize(CENT):
        raise ValueError(f"{value!r} has more than two decimal places.")
    return amount.quantize(CENT)


def allocate(amount: Decimal, weights: dict) -> dict:
    """Split ``amount`` across ``weights`` keys by the largest-remainder method.

    Parts are whole cents and sum exactly to ``amount``. Keys with zero or
    negative weight get nothing. If no key has a positive weight, the amount
    is split equally. Ties on the remainder go to the smallest key, so the
    result is deterministic.
    """
    amount = to_money(amount)
    if not weights:
        raise ValueError("Cannot allocate across nobody.")
    positive = {k: Decimal(w) for k, w in weights.items() if Decimal(w) > 0}
    if not positive:
        positive = {k: Decimal(1) for k in weights}
    total_weight = sum(positive.values())
    cents = int(amount / CENT)
    shares, remainders = {}, []
    for key in sorted(positive):
        exact = Decimal(cents) * positive[key] / total_weight
        whole = int(exact.to_integral_value(rounding=ROUND_DOWN))
        shares[key] = whole
        remainders.append((exact - whole, key))
    leftover = cents - sum(shares.values())
    for _, key in sorted(remainders, key=lambda r: (-r[0], r[1]))[:leftover]:
        shares[key] += 1
    return {k: Decimal(v) * CENT for k, v in shares.items() if v}
