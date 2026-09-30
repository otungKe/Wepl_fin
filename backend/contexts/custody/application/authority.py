"""Resolves the member making a correction and refuses anyone not granted
``correct_records`` by their group (ADR-0011)."""
from contexts.communities.public import CommunityError, MembershipView, membership
from contexts.governance.public import Capability, holds

from ..contract import CustodyError
from ..domain.authority import Actor, pair_refusal, refusal


def _actor(membership_id: int) -> tuple[Actor, MembershipView]:
    try:
        m = membership(membership_id)
    except CommunityError:
        raise CustodyError("Not authorised: unknown member.") from None
    return Actor(membership_id=m.id, group_id=m.group_id, active=m.is_active,
                 may_correct=holds(m.id, Capability.CORRECT_RECORDS)), m


def corrector(membership_id: int, group_id: int, *, beneficiaries=()) -> MembershipView:
    actor, view = _actor(membership_id)
    if reason := refusal(actor, group_id=group_id, beneficiary_ids=frozenset(beneficiaries)):
        raise CustodyError(f"Not authorised: the caller {reason}.")
    return view


def maker_checker(maker_id: int, checker_id: int, group_id: int) -> tuple[MembershipView, MembershipView]:
    (maker, mv), (checker, cv) = _actor(maker_id), _actor(checker_id)
    if reason := pair_refusal(maker, checker, group_id=group_id):
        raise CustodyError(f"Not authorised: {reason}." if "same member" in reason
                           else f"Not authorised: a signer {reason}.")
    return mv, cv
