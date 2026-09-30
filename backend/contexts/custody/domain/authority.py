"""Who may correct the books. Corrections change what members are owed, so
only an active official of the account's own group may make them, never in
their own favour, and opening balances need a second official (maker-checker).
There are no operator accounts yet; see the wepl-security skill."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Actor:
    membership_id: int
    group_id: int
    active: bool
    official: bool


def refusal(actor: Actor, *, group_id: int, beneficiary_ids: frozenset[int] = frozenset()) -> str | None:
    """Why ``actor`` may not correct this group's books, or None if they may."""
    if actor.group_id != group_id:
        return "is not a member of this group"
    if not actor.active:
        return "is not an active member"
    if not actor.official:
        return "is not an official of this group"
    if actor.membership_id in beneficiary_ids:
        return "cannot make a correction in their own favour"
    return None


def pair_refusal(maker: Actor, checker: Actor, *, group_id: int) -> str | None:
    """Maker-checker: two different officials of the group. Officials usually
    hold balances themselves, so the second signature is the control here."""
    if maker.membership_id == checker.membership_id:
        return "the same official cannot also confirm"
    for who in (maker, checker):
        if reason := refusal(who, group_id=group_id):
            return reason
    return None
