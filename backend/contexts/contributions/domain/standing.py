"""Where a member stands against a fund's contribution rule (ADR-0022).

Derived every time from the periods due and the member's pay-ins; nothing
is stored. Each setting that changes the answer is the group's own choice:
which amount a payment clears first, whether paying more than is due
covers later periods, the late fine, and what happens to a leaver's arrears.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from contexts.governance.contract import ExtraPayments, FineKind, LateFine, PaymentOrder
from contexts.shared_kernel.money import CENT, Money


@dataclass(frozen=True)
class Standing:
    due: Money                          # everything due on or before the day asked about
    paid: Money                         # the part of it that payments cleared
    arrears: Money                      # due and not paid
    paid_ahead: Money                   # paid towards periods not due yet
    overdue: tuple[tuple[date, Money], ...]   # (due date, still owed), oldest first
    fines: tuple[tuple[date, Money], ...]     # (due date of the late period, fine)
    written_off: Money = Money.zero()   # a leaver's arrears and fines, when the group writes them off

    @property
    def fines_total(self) -> Money:
        return sum((f for _, f in self.fines), Money.zero(self.due.currency))


def _min(a: Money, b: Money) -> Money:
    return a if a <= b else b


def standing(periods: list[tuple[date, Money]], payments: list[tuple[date, Money]], *, as_of: date,
             order: PaymentOrder, extra: ExtraPayments, fine: LateFine, write_off: bool = False) -> Standing:
    """``periods`` are (due date, amount), oldest first, and may include the
    next one after ``as_of``. A payment counts for every period whose time
    has begun: the period running up to a due date begins the day after the
    one before it. ``write_off`` is for a leaver whose group writes arrears off."""
    zero = Money.zero()
    remaining = [amount for _, amount in periods]
    cleared: list[list[tuple[date, Money]]] = [[] for _ in periods]
    state = {"open": 0, "credit": zero}

    def clear(i: int, most: Money, on: date) -> Money:
        take = _min(most, remaining[i])
        if take.is_positive:
            remaining[i] -= take
            cleared[i].append((on, take))
        return take

    def open_until(n: int, on: date) -> None:
        while state["open"] < n:
            i = state["open"]
            state["open"] += 1
            if extra is ExtraPayments.PAY_AHEAD:
                state["credit"] -= clear(i, state["credit"], min(on, periods[i][0]))

    for on, amount in sorted(payments, key=lambda p: p[0]):
        current = next((i for i, (due, _) in enumerate(periods) if due >= on), len(periods) - 1)
        open_until(current + 1, on)
        left = amount
        for i in (range(state["open"]) if order is PaymentOrder.OLDEST_FIRST else reversed(range(state["open"]))):
            left -= clear(i, left, on)
        if extra is ExtraPayments.PAY_AHEAD:
            state["credit"] += left  # otherwise it is savings only
    owed = [i for i, (due, _) in enumerate(periods) if due <= as_of]
    open_until(len(owed), as_of)

    due = sum((periods[i][1] for i in owed), zero)
    arrears = sum((remaining[i] for i in owed), zero)
    ahead = sum((a - remaining[i] for i, (d, a) in enumerate(periods) if d > as_of), zero) + state["credit"]
    fines = tuple(f for i in owed if (f := _fine(fine, periods[i], cleared[i], as_of)) is not None)
    result = Standing(due=due, paid=due - arrears, arrears=arrears, paid_ahead=ahead,
                      overdue=tuple((periods[i][0], remaining[i]) for i in owed if remaining[i].is_positive),
                      fines=fines)
    if write_off:
        return Standing(due=due, paid=result.paid, arrears=zero, paid_ahead=ahead, overdue=(), fines=(),
                        written_off=arrears + result.fines_total)
    return result


def _fine(fine: LateFine, period: tuple[date, Money], cleared: list[tuple[date, Money]], as_of: date):
    """A fine for one late period, once: what was still owed when the
    group's grace days ran out."""
    if fine.kind is FineKind.NONE:
        return None
    due_on, amount = period
    deadline = due_on + timedelta(days=fine.grace_days)
    if deadline >= as_of:
        return None
    owed = amount - sum((a for on, a in cleared if on <= deadline), Money.zero(amount.currency))
    if not owed.is_positive:
        return None
    if fine.kind is FineKind.FIXED:
        return due_on, Money.of(fine.value)
    value = (owed.amount * fine.value / Decimal(100)).quantize(CENT, rounding=ROUND_HALF_UP)
    return (due_on, Money(value, amount.currency)) if value > 0 else None
