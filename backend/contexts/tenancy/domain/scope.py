"""How a piece of persistent data relates to tenants (foundational decision 4).
Every model declares one; the architecture test checks the database agrees."""
from enum import StrEnum


class TenantScope(StrEnum):
    GLOBAL = "global"              # the same for everyone, e.g. reference data or a test double
    TENANT_SCOPED = "tenant"       # belongs to exactly one tenant; row-level security enforced
    USER_SCOPED = "user"           # belongs to a person across tenants, e.g. their phone number
    SYSTEM = "system"              # the platform's own records about tenants, e.g. the tenant list


class TenancyError(RuntimeError):
    """A tenant boundary was about to be crossed without being declared."""


def entry_refusal(active_tenant: int | None, system: bool, wanted: int | None) -> str | None:
    """Why entering ``wanted`` (None = system scope) from the current scope is
    refused. Re-entering the same scope is allowed; switching is not: finish
    one tenant's work before starting another's."""
    if wanted is None:
        if active_tenant is not None:
            return f"cannot start a cross-tenant operation while acting for tenant {active_tenant}"
        return None
    if system:
        return "cannot act for a tenant inside a cross-tenant operation"
    if active_tenant is not None and active_tenant != wanted:
        return f"already acting for tenant {active_tenant}; cannot switch to tenant {wanted}"
    return None
