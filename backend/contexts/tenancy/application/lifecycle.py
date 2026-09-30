from contexts.audit.public import record

from ..contract import TenantView
from ..infrastructure.models import Tenant
from .context import cross_tenant


def provision_tenant(name: str, *, actor: str) -> TenantView:
    """Create the tenant row for a group being founded. Only
    ``communities.create_group`` calls this: a tenant without its group cannot
    commit (ADR-0013). A system operation: no tenant exists yet to act for."""
    with cross_tenant(f"provision tenant {name!r}", actor=actor):
        t = Tenant.objects.create(name=name)
        record(actor, "tenancy.tenant_provisioned", target_type="tenant", target_id=t.pk, data={"name": name})
    return TenantView(id=t.pk, name=t.name)


def tenant_ids(*, reason: str, actor: str) -> list[int]:
    """Every tenant, for a job that then acts for each in turn. Declared and audited."""
    with cross_tenant(reason, actor=actor):
        return list(Tenant.objects.order_by("pk").values_list("pk", flat=True))
