"""Row-level security only binds roles that are not superuser or BYPASSRLS
(ADR-0009). Refuse to run as one."""
from django.core.checks import Error, Tags, register
from django.db import connections

from .session import role_bypasses_rls


@register(Tags.database)
def database_role_is_bound_by_rls(app_configs, databases=None, **kwargs):
    errors = []
    for alias in databases or []:
        if connections[alias].vendor == "postgresql" and role_bypasses_rls(alias):
            errors.append(Error(f"Database role for '{alias}' is a superuser or has BYPASSRLS, so tenant isolation "
                                "would not be enforced.", hint="Connect as a role like wepl_app (see README).",
                                id="tenancy.E001"))
    return errors
