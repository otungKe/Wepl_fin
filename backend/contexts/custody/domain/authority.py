"""Who may correct the books. Corrections change what members are owed, so
only an active member of the account's own group who has been granted
``correct_records`` may make them (ADR-0011), never in their own favour, and
opening balances need a second, different holder (maker-checker). A title
such as "Treasurer" grants nothing. There are no operator accounts yet; see
the wepl-security skill."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Actor:
    membership_id: int
    group_id: int
    active: bool
    may_correct: bool


def refusal(actor: Actor, *, group_id: int, beneficiary_ids: frozenset[int] = frozenset()) -> str | None:
    """Why ``actor`` may not correct this group's books, or None if they may."""
    if actor.group_id != group_id:
        return "is not a member of this group"
    if not actor.active:
        return "is not an active member"
    if not actor.may_correct:
        return "has not been granted correct_records"
    if actor.membership_id in beneficiary_ids:
        return "cannot make a correction in their own favour"
    return None


def pair_refusal(maker: Actor, checker: Actor, *, group_id: int) -> str | None:
    """Maker-checker: two different members holding correct_records. They
    usually hold balances themselves, so the second signature is the control."""
    if maker.membership_id == checker.membership_id:
        return "the same member cannot also confirm"
    for who in (maker, checker):
        if reason := refusal(who, group_id=group_id):
            return reason
    return None
