"""Use cases: create a group; add a member, change their title, record that they left."""
from django.db import transaction

from contexts.audit.public import record
from contexts.identity.public import register_person
from contexts.tenancy.public import require_tenant

from ..contract import CommunityError, FundView, GroupView, MembershipView
from ..domain.group import Segment
from ..domain.membership import MembershipError, clean_title, ensure_can_leave, member_code
from ..infrastructure.models import Fund, Group, Membership
from .queries import fund_view, group_view, membership


@transaction.atomic  # a group never exists without its first fund
def create_group(name: str, *, segment: str = Segment.SAVINGS, fund_name: str = "Main fund",
                 currency: str = "KES", actor: str) -> tuple[GroupView, FundView]:
    """Create the group of the current tenant. A group is a tenant (ADR-0010):
    provision the tenant first, then create its one group inside it."""
    Segment(segment)
    require_tenant()
    if Group.objects.exists():  # row-level security shows only this tenant's group
        raise CommunityError("This tenant already has its group; each group is its own tenant.")
    group = Group.objects.create(name=name.strip(), segment=segment)
    fund = Fund.objects.create(group=group, name=fund_name, currency=currency)
    record(actor, "group.created", target_type="group", target_id=group.pk, group_id=group.pk,
           data={"fund_id": fund.pk, "segment": segment})
    return group_view(group.pk), fund_view(fund.pk)


@transaction.atomic  # the group row lock hands out each member sequence exactly once
def add_member(group_id: int, *, msisdn: str, name: str, title: str = "", actor: str) -> MembershipView:
    """Add a member. ``title`` is the group's own optional label for them; it
    grants no authority (grant capabilities in governance for that)."""
    try:
        title = clean_title(title)
    except MembershipError as exc:
        raise CommunityError(str(exc)) from None
    person = register_person(msisdn, name)
    group = Group.objects.select_for_update().get(pk=group_id)
    if Membership.objects.filter(group=group, person_id=person.id, status="active").exists():
        raise CommunityError(f"{person.msisdn} is already an active member of {group.name}.")
    group.last_member_sequence += 1
    group.save(update_fields=["last_member_sequence"])
    code = member_code(group.last_member_sequence)
    m = Membership.objects.create(group=group, person_id=person.id, title=title, member_code=code)
    record(actor, "member.added", target_type="membership", target_id=m.pk, group_id=group_id,
           data={"title": title, "code": code})
    return membership(m.pk)


@transaction.atomic
def set_title(membership_id: int, title: str | None, *, actor: str) -> MembershipView:
    """Change a member's label, e.g. after a change of officials. It changes
    no authority: grant or revoke capabilities in governance for that. The
    audit trail keeps every earlier title."""
    m = Membership.objects.select_for_update().get(pk=membership(membership_id).id)
    try:
        title = clean_title(title)
    except MembershipError as exc:
        raise CommunityError(str(exc)) from None
    if title != m.title:
        record(actor, "member.title_changed", target_type="membership", target_id=m.pk, group_id=m.group_id,
               data={"from": m.title, "to": title})
        m.title = title
        m.save(update_fields=["title"])
    return membership(m.pk)


@transaction.atomic
def leave_group(membership_id: int, *, actor: str) -> MembershipView:
    """Record that a member left. Final: a returning person joins again with a
    new code. Their capabilities lapse with it; settling their balance under
    the constitution's leaving rule is a separate, ledger matter."""
    m = Membership.objects.select_for_update().get(pk=membership(membership_id).id)
    try:
        ensure_can_leave(m.status)
    except MembershipError as exc:
        raise CommunityError(str(exc)) from None
    m.status = "left"
    m.save(update_fields=["status"])
    record(actor, "member.left", target_type="membership", target_id=m.pk, group_id=m.group_id,
           data={"code": m.member_code})
    return membership(m.pk)
