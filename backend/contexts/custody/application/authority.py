"""Resolves the official making a correction and refuses anyone else."""
from contexts.communities.public import CommunityError, MembershipView, membership

from ..contract import CustodyError
from ..domain.authority import Actor, pair_refusal, refusal


def _actor(membership_id: int) -> tuple[Actor, MembershipView]:
    try:
        m = membership(membership_id)
    except CommunityError:
        raise CustodyError("Not authorised: unknown official.") from None
    return Actor(membership_id=m.id, group_id=m.group_id, active=m.is_active, official=m.is_official), m


def official(membership_id: int, group_id: int, *, beneficiaries=()) -> MembershipView:
    actor, view = _actor(membership_id)
    if reason := refusal(actor, group_id=group_id, beneficiary_ids=frozenset(beneficiaries)):
        raise CustodyError(f"Not authorised: the caller {reason}.")
    return view


def two_officials(maker_id: int, checker_id: int, group_id: int) -> tuple[MembershipView, MembershipView]:
    (maker, mv), (checker, cv) = _actor(maker_id), _actor(checker_id)
    if reason := pair_refusal(maker, checker, group_id=group_id):
        raise CustodyError(f"Not authorised: {reason}." if "same official" in reason
                           else f"Not authorised: an official {reason}.")
    return mv, cv
