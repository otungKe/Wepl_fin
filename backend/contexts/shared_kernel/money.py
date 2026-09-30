"""Money as a value: an exact decimal amount in one currency.

Amounts are held to the currency's minor unit (two places for KES) and are
never floats. The only rounding anywhere is in ``Money.allocate``, which splits
an amount exactly: the parts always add back to the whole.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import total_ordering
from decimal import ROUND_DOWN, Decimal

DEFAULT_CURRENCY = "KES"
CENT = Decimal("0.01")


class MoneyError(ValueError):
    pass


def _parse(value) -> Decimal:
    if isinstance(value, float):
        raise MoneyError("Money must not be a float; pass a string or Decimal.")
    try:
        amount = Decimal(str(value))
    except Exception as exc:
        raise MoneyError(f"{value!r} is not an amount.") from exc
    if not amount.is_finite():
        raise MoneyError(f"{value!r} is not a finite amount.")
    if amount != amount.quantize(CENT):
        raise MoneyError(f"{value!r} has more than two decimal places.")
    return amount.quantize(CENT)


@total_ordering
@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str = DEFAULT_CURRENCY

    def __post_init__(self):
        object.__setattr__(self, "amount", _parse(self.amount))

    @classmethod
    def of(cls, value, currency: str = DEFAULT_CURRENCY) -> Money:
        return value if isinstance(value, Money) else cls(value, currency)

    @classmethod
    def zero(cls, currency: str = DEFAULT_CURRENCY) -> Money:
        return cls(Decimal("0.00"), currency)

    def _same(self, other: Money) -> None:
        if not isinstance(other, Money):
            raise TypeError(f"Cannot combine Money with {type(other).__name__}.")
        if other.currency != self.currency:
            raise MoneyError(f"Cannot combine {self.currency} with {other.currency}.")

    def __add__(self, other: Money) -> Money:
        self._same(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._same(other)
        return Money(self.amount - other.amount, self.currency)

    def __lt__(self, other: Money) -> bool:
        self._same(other)
        return self.amount < other.amount

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    @property
    def is_positive(self) -> bool:
        return self.amount > 0

    @property
    def is_zero(self) -> bool:
        return self.amount == 0

    def allocate(self, weights: dict) -> dict:
        """Split across ``weights`` keys by the largest-remainder method.

        Parts are whole cents and sum exactly to the whole. Keys with zero or
        negative weight get nothing; if no key has a positive weight, the split
        is equal. Remainder ties go to the smallest key, so results are
        deterministic. Keys that would receive nothing are left out.
        """
        if not weights:
            raise MoneyError("Cannot allocate across nobody.")
        if self.amount < 0:
            raise MoneyError("Cannot allocate a negative amount.")
        positive = {k: Decimal(w) for k, w in weights.items() if Decimal(w) > 0}
        if not positive:
            positive = {k: Decimal(1) for k in weights}
        total = sum(positive.values())
        cents = int(self.amount / CENT)
        shares, remainders = {}, []
        for key in sorted(positive):
            exact = Decimal(cents) * positive[key] / total
            whole = int(exact.to_integral_value(rounding=ROUND_DOWN))
            shares[key] = whole
            remainders.append((exact - whole, key))
        for _, key in sorted(remainders, key=lambda r: (-r[0], r[1]))[: cents - sum(shares.values())]:
            shares[key] += 1
        return {k: Money(Decimal(v) * CENT, self.currency) for k, v in shares.items() if v}

    def __str__(self) -> str:
        return f"{self.currency} {self.amount:,.2f}"
