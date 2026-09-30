from contexts.identity.public import people

from ..contract import CommunityError, FundView, GroupView, MembershipView
from ..infrastructure.models import Fund, Group, Membership


def group_view(group_id: int) -> GroupView:
    g = Group.objects.get(pk=group_id)
    return GroupView(id=g.pk, name=g.name, segment=g.segment)


def fund_view(fund_id: int) -> FundView:
    f = Fund.objects.get(pk=fund_id)
    return FundView(id=f.pk, group_id=f.group_id, name=f.name, currency=f.currency)


def _views(rows) -> list[MembershipView]:
    rows = list(rows)
    who = people(r.person_id for r in rows)
    return [MembershipView(id=r.pk, group_id=r.group_id, person_id=r.person_id, msisdn=who[r.person_id].msisdn,
                           name=who[r.person_id].name, role=r.role, status=r.status, code=r.member_code)
            for r in rows]


def membership(membership_id: int) -> MembershipView:
    """Raises CommunityError for an id that does not exist or, under row-level
    security, belongs to another tenant: the two are indistinguishable."""
    views = _views(Membership.objects.filter(pk=membership_id))
    if not views:
        raise CommunityError(f"Unknown member {membership_id}.")
    return views[0]


def members(group_id: int, *, active_only: bool = True) -> list[MembershipView]:
    qs = Membership.objects.filter(group_id=group_id)
    if active_only:
        qs = qs.filter(status="active")
    return _views(qs.order_by("id"))
