"""Fines paid against fines owed (ADR-0022; Harry, 2026-10-05).

A fine is an amount owed until paid; it moves no money. A member pays it
into the fund the group named for fines. Fines from every rule that names
the same fund are settled together, the oldest first.
"""
from __future__ import annotations

from datetime import date

from contexts.shared_kernel.money import Money


def settle(fines: dict[int, tuple[tuple[date, Money], ...]], paid: Money) -> tuple[dict[int, Money], Money]:
    """``fines`` maps each fund to its fines (due date, amount); ``paid`` is
    everything the member paid into the fines fund. Returns what was paid
    against each fund's fines, and anything paid beyond all of them."""
    settled = {fund: Money.zero(paid.currency) for fund in fines}
    left = paid
    for _, fund, amount in sorted((on, fund, a) for fund, items in fines.items() for on, a in items):
        take = amount if amount <= left else left
        settled[fund] += take
        left -= take
    return settled, left
