"""Use case: found a group. The group is a tenant (ADR-0010, ADR-0013)."""
from django.db import IntegrityError, transaction

from contexts.audit.public import record
from contexts.tenancy.public import current_tenant, provision_tenant, tenant

from ..contract import CommunityError, GroupView
from ..infrastructure.models import Group
from .queries import group_view


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
        group = _found(name)
        record(actor, "group.created", target_type="group", target_id=group.pk, group_id=group.pk,
               data={"tenant_id": identity.id})
        return group_view(group.pk)


def _found(name: str) -> Group:
    """The database draws the payment code from 90,000. A clash with an
    existing group is refused by its unique key; draw again."""
    for attempt in range(20):
        try:
            with transaction.atomic():
                return Group.objects.create(name=name)
        except IntegrityError as exc:
            if "payment_code" not in str(exc) or attempt == 19:
                raise
    raise AssertionError("unreachable")
