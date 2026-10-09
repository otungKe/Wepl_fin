from contexts.identity.public import people
from contexts.tenancy.public import current_tenant, require_cross_tenant

from ..contract import CommunityError, FundView, GroupView, MembershipView
from ..infrastructure.models import Fund, Group, Membership


def _scoped() -> None:
    """Every query reads inside a tenant or a declared cross-tenant operation.
    Anywhere else row-level security shows nothing, and an empty list must
    never be mistaken for "the group has no funds" (review of 2026-10-06, I7)."""
    if current_tenant() is None:
        require_cross_tenant()


def group_view(group_id: int) -> GroupView:
    """Raises CommunityError for an unknown group or, under row-level
    security, another tenant's: the two are indistinguishable."""
    _scoped()
    g = Group.objects.filter(pk=group_id).first()
    if g is None:
        raise CommunityError(f"Unknown group {group_id}.")
    return GroupView(id=g.pk, tenant_id=g.tenant_id, name=g.name)


def groups() -> list[GroupView]:
    """The groups visible here: under row-level security, the current
    tenant's one group (ADR-0010)."""
    _scoped()
    return [GroupView(id=g.pk, tenant_id=g.tenant_id, name=g.name) for g in Group.objects.order_by("pk")]


def fund_view(fund_id: int) -> FundView:
    """Raises CommunityError for an unknown fund or, under row-level
    security, another tenant's: the two are indistinguishable."""
    _scoped()
    f = Fund.objects.filter(pk=fund_id).first()
    if f is None:
        raise CommunityError(f"Unknown fund {fund_id}.")
    return _fund(f)


def _fund(f: Fund) -> FundView:
    return FundView(id=f.pk, group_id=f.group_id, name=f.name, currency=f.currency, status=f.status, code=f.code)


def funds(group_id: int, *, open_only: bool = True) -> list[FundView]:
    _scoped()
    qs = Fund.objects.filter(group_id=group_id)
    if open_only:
        qs = qs.filter(status="open")
    return [_fund(f) for f in qs.order_by("pk")]


def _views(rows) -> list[MembershipView]:
    rows = list(rows)
    who = people(r.person_id for r in rows)
    return [MembershipView(id=r.pk, group_id=r.group_id, person_id=r.person_id, msisdn=who[r.person_id].msisdn,
                           name=who[r.person_id].name, title=r.title, status=r.status, code=r.member_code,
                           joined_at=r.joined_at, left_at=r.left_at)
            for r in rows]


def membership(membership_id: int) -> MembershipView:
    """Raises CommunityError for an id that does not exist or, under row-level
    security, belongs to another tenant: the two are indistinguishable."""
    _scoped()
    views = _views(Membership.objects.filter(pk=membership_id))
    if not views:
        raise CommunityError(f"Unknown member {membership_id}.")
    return views[0]


def members(group_id: int, *, active_only: bool = True) -> list[MembershipView]:
    _scoped()
    qs = Membership.objects.filter(group_id=group_id)
    if active_only:
        qs = qs.filter(status="active")
    return _views(qs.order_by("id"))
