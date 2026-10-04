"""Who shares in what the custodian does to a fund (ADR-0014).

A member shares in an event by where their membership stood on the day it
happened, not on the day the statement arrived:

- a member in the group that day shares interest, bank charges and pro-rata
  payouts;
- a member who had already left never shares in a payout, and shares
  interest and charges only if the group's rule in force on the day they
  left was ``SHARES_UNTIL_PAID`` and their balance is still above zero;
- a member who joined after the event shares in nothing from it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from contexts.governance.contract import LeaverBalances
from contexts.shared_kernel.money import Money


class Event(StrEnum):
    RETURNS = "returns"  # interest and bank charges
    PAYOUT = "payout"    # a pro-rata payout


@dataclass(frozen=True)
class Spell:
    membership_id: int
    joined_at: datetime | None
    left_at: datetime | None
    leaver_rule: LeaverBalances | None = None  # the rule in force when they left


def sharers(spells: list[Spell], *, at: datetime, event: Event, balances: dict[int, Money]) -> list[int]:
    chosen = []
    for s in spells:
        if s.joined_at is not None and s.joined_at > at:
            continue
        if s.left_at is None or s.left_at > at:
            chosen.append(s.membership_id)
        elif (event is Event.RETURNS and s.leaver_rule is LeaverBalances.SHARES_UNTIL_PAID
              and (b := balances.get(s.membership_id)) is not None and b.amount > 0):
            chosen.append(s.membership_id)
    return sorted(chosen)
