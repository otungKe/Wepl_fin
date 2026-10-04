"""Who shares in what the custodian does to a fund (ADR-0014).

A member shares in an event by where their membership stood on the day it
happened, not on the day the statement arrived. For leavers, every choice is
the group's own (its constitution); which version of it applies is the
caller's to resolve (``leaver_rule_version``):

- a member in the group that day shares interest, bank charges and pro-rata
  payouts;
- a member who had already left shares interest and charges only if the
  group's leaver rule is ``SHARES_UNTIL_PAID`` and their balance is still
  above zero, and bears a pro-rata payout only as the group's
  ``leaver_payouts`` choice says;
- a member who joined after the event shares in nothing from it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from contexts.governance.contract import LeaverBalances, LeaverPayouts
from contexts.shared_kernel.money import Money


class Event(StrEnum):
    RETURNS = "returns"  # interest and bank charges
    PAYOUT = "payout"    # a pro-rata payout


@dataclass(frozen=True)
class Spell:
    membership_id: int
    joined_at: datetime | None
    left_at: datetime | None
    leaver_rule: LeaverBalances | None = None     # the group's rule that applies to this leaver
    leaver_payouts: LeaverPayouts | None = None


def sharers(spells: list[Spell], *, at: datetime, event: Event, balances: dict[int, Money],
            approved_at: datetime | None = None) -> list[int]:
    """``approved_at`` is when the group approved a payout (its mandate)."""
    chosen = []
    for s in spells:
        if s.joined_at is not None and s.joined_at > at:
            continue
        if s.left_at is None or s.left_at > at or _leaver_shares(s, event, balances, approved_at):
            chosen.append(s.membership_id)
    return sorted(chosen)


def _leaver_shares(s: Spell, event: Event, balances: dict[int, Money], approved_at: datetime | None) -> bool:
    if event is Event.RETURNS:
        b = balances.get(s.membership_id)
        return s.leaver_rule is LeaverBalances.SHARES_UNTIL_PAID and b is not None and b.amount > 0
    if s.leaver_payouts is LeaverPayouts.ALWAYS:
        return True
    return (s.leaver_payouts is LeaverPayouts.APPROVED_BEFORE_LEAVING and approved_at is not None
            and approved_at < s.left_at)
