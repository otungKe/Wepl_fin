from contexts.identity.public import people

from ..contract import CommunityError, FundView, GroupView, MembershipView
from ..infrastructure.models import Fund, Group, Membership


def group_view(group_id: int) -> GroupView:
    """Raises CommunityError for an unknown group or, under row-level
    security, another tenant's: the two are indistinguishable."""
    g = Group.objects.filter(pk=group_id).first()
    if g is None:
        raise CommunityError(f"Unknown group {group_id}.")
    return _group(g)


def _group(g: Group) -> GroupView:
    return GroupView(id=g.pk, tenant_id=g.tenant_id, name=g.name, payment_code=g.payment_code)


def group_for_payment_code(code: str) -> GroupView | None:
    """The group whose payment code this is, or None. Only finds groups the
    caller can see: its own inside a tenant, any in a declared cross-tenant
    operation (ADR-0018 routing)."""
    g = Group.objects.filter(payment_code=code.strip()).first()
    return _group(g) if g else None


def fund_view(fund_id: int) -> FundView:
    """Raises CommunityError for an unknown fund or, under row-level
    security, another tenant's: the two are indistinguishable."""
    f = Fund.objects.filter(pk=fund_id).first()
    if f is None:
        raise CommunityError(f"Unknown fund {fund_id}.")
    return FundView(id=f.pk, group_id=f.group_id, name=f.name, currency=f.currency, status=f.status)


def _views(rows) -> list[MembershipView]:
    rows = list(rows)
    who = people(r.person_id for r in rows)
    return [MembershipView(id=r.pk, group_id=r.group_id, person_id=r.person_id, msisdn=who[r.person_id].msisdn,
                           name=who[r.person_id].name, title=r.title, status=r.status, code=r.member_code)
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
