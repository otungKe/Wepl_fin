from django.db import transaction

from contexts.audit.public import record

from ..domain.rules import ConstitutionRules
from ..infrastructure.models import Constitution


@transaction.atomic  # version numbers are assigned under a lock on the latest version
def adopt_constitution(group_id: int, rules: dict, *, actor: str) -> int:
    """Adopt a new version. Earlier versions stay, and proposals keep the
    version they were made under. (Pilot: the group signs it off on paper.)"""
    parsed = ConstitutionRules.parse(rules)
    latest = Constitution.objects.select_for_update().filter(group_id=group_id).order_by("-version").first()
    version = latest.version + 1 if latest else 1
    c = Constitution.objects.create(group_id=group_id, version=version, rules=parsed.to_dict(), adopted_by=actor)
    record(actor, "constitution.adopted", target_type="constitution", target_id=c.pk, group_id=group_id,
           data={"version": version, "rules": parsed.to_dict()})
    return version


def current_constitution(group_id: int) -> Constitution | None:
    return Constitution.objects.filter(group_id=group_id).order_by("-version").first()


def current_rules(group_id: int) -> ConstitutionRules | None:
    c = current_constitution(group_id)
    return ConstitutionRules.parse(c.rules) if c else None
