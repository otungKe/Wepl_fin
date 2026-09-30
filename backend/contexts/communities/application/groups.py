"""Use cases: create a group, add a member."""
from django.db import transaction

from contexts.audit.public import record
from contexts.identity.public import register_person

from ..contract import FundView, GroupView, MembershipView
from ..domain.membership import Role, Segment, member_code
from ..infrastructure.models import Fund, Group, Membership
from .queries import fund_view, group_view, membership


class CommunityError(ValueError):
    pass


@transaction.atomic  # a group never exists without its first fund
def create_group(name: str, *, segment: str = Segment.SAVINGS, fund_name: str = "Main fund",
                 currency: str = "KES", actor: str) -> tuple[GroupView, FundView]:
    Segment(segment)
    group = Group.objects.create(name=name.strip(), segment=segment)
    fund = Fund.objects.create(group=group, name=fund_name, currency=currency)
    record(actor, "group.created", target_type="group", target_id=group.pk, group_id=group.pk,
           data={"fund_id": fund.pk, "segment": segment})
    return group_view(group.pk), fund_view(fund.pk)


@transaction.atomic  # the group row lock makes member codes gap-free and unique
def add_member(group_id: int, *, msisdn: str, name: str, role: str = Role.MEMBER, actor: str) -> MembershipView:
    Role(role)
    person = register_person(msisdn, name)
    group = Group.objects.select_for_update().get(pk=group_id)
    if Membership.objects.filter(group=group, person_id=person.id, status="active").exists():
        raise CommunityError(f"{person.msisdn} is already an active member of {group.name}.")
    code = member_code(Membership.objects.filter(group=group).count() + 1)
    m = Membership.objects.create(group=group, person_id=person.id, role=role, member_code=code)
    record(actor, "member.added", target_type="membership", target_id=m.pk, group_id=group_id,
           data={"role": role, "code": code})
    return membership(m.pk)
