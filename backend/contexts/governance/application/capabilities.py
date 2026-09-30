"""Use cases: a group grants or revokes what a member may do (ADR-0011)."""
from django.db import transaction

from contexts.audit.public import record
from contexts.communities.public import members, membership

from ..contract import GovernanceError
from ..domain.capabilities import Capability, current
from ..infrastructure.models import CapabilityChange


def capabilities_of(membership_id: int) -> frozenset[Capability]:
    """What this member may do now. A member who has left may do nothing."""
    if not membership(membership_id).is_active:
        return frozenset()
    changes = CapabilityChange.objects.filter(membership_id=membership_id).order_by("id")
    return current(changes.values_list("capability", "granted"))


def holds(membership_id: int, capability: Capability) -> bool:
    return Capability(capability) in capabilities_of(membership_id)


def holders(group_id: int, capability: Capability) -> list[int]:
    return [m.id for m in members(group_id) if holds(m.id, capability)]


@transaction.atomic
def _change(membership_id: int, capability: str, *, granted: bool, actor: str) -> frozenset[Capability]:
    try:
        capability = Capability(capability)
    except ValueError:
        raise GovernanceError(f"Unknown capability {capability!r}.") from None
    m = membership(membership_id)
    if granted and not m.is_active:
        raise GovernanceError("Only an active member can be granted a capability.")
    if (capability in capabilities_of(m.id)) == granted:
        return capabilities_of(m.id)  # already so: repeating a grant or revocation changes nothing
    CapabilityChange.objects.create(group_id=m.group_id, membership_id=m.id, capability=capability,
                                    granted=granted, changed_by=actor)
    record(actor, "capability.granted" if granted else "capability.revoked", target_type="membership",
           target_id=m.id, group_id=m.group_id, data={"capability": capability.value})
    return capabilities_of(m.id)


def grant(membership_id: int, capability: str, *, actor: str) -> frozenset[Capability]:
    """Pilot: operators record the grants the group's constitution names.
    Once login lands, grants become a governed decision of the group."""
    return _change(membership_id, capability, granted=True, actor=actor)


def revoke(membership_id: int, capability: str, *, actor: str) -> frozenset[Capability]:
    return _change(membership_id, capability, granted=False, actor=actor)
