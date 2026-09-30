"""Use cases: found a group; open a fund; add a member, change their title,
record that they left."""
from django.db import IntegrityError, transaction

from contexts.audit.public import record
from contexts.identity.public import register_person
from contexts.tenancy.public import current_tenant, provision_tenant, tenant

from ..contract import CommunityError, FundView, GroupView, MembershipView
from ..domain.membership import MembershipError, clean_title, ensure_can_leave, member_code
from ..infrastructure.models import Fund, Group, Membership
from .queries import fund_view, group_view, membership


@transaction.atomic  # the group and its tenant identity exist together or not at all
def create_group(name: str, *, actor: str) -> GroupView:
    """Found a group. The group *is* a tenant (ADR-0010, ADR-0013): founding
    it establishes its tenant identity, through tenancy, and creates the group
    under it, in one transaction. So it is called outside any tenant, never
    inside one: a group is not something created within another boundary.
    Act for it afterwards with ``tenancy.public.tenant(group.tenant_id)``."""
    name = name.strip()
    if not name:
        raise CommunityError("A group needs a name.")
    if current_tenant() is not None:
        raise CommunityError("A group is founded outside any tenant, because it becomes one.")
    identity = provision_tenant(name, actor=actor)
    with tenant(identity.id):
        group = Group.objects.create(name=name)
        record(actor, "group.created", target_type="group", target_id=group.pk, group_id=group.pk,
               data={"tenant_id": identity.id})
        return group_view(group.pk)


@transaction.atomic
def open_fund(group_id: int, *, name: str = "Main fund", currency: str = "KES", actor: str) -> FundView:
    """Open one of the group's named pools of money ("Main savings",
    "Welfare"). A group may have none yet, or several (ADR-0013). Balances
    are the ledger's; this only names the pool."""
    group = group_view(group_id)
    name = name.strip()
    if not name:
        raise CommunityError("A fund needs a name.")
    try:
        with transaction.atomic():
            fund = Fund.objects.create(group_id=group.id, name=name, currency=currency)
    except IntegrityError:
        raise CommunityError(f"{group.name} already has a fund called {name!r}.") from None
    record(actor, "fund.opened", target_type="fund", target_id=fund.pk, group_id=group.id,
           data={"name": name, "currency": currency})
    return fund_view(fund.pk)


@transaction.atomic  # the group row lock, taken here and by the database trigger, serialises joins
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
    # PostgreSQL takes the sequence itself on insert and refuses any other
    # code (0007), so every path that creates a membership allocates alike.
    code = member_code(group.last_member_sequence + 1)
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
