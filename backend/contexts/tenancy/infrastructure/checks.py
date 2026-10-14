"""The database role the application connects as.

E001: row-level security only binds roles that are not superuser or
BYPASSRLS (ADR-0009). E002: the role must not own the tables or hold
privileges that would let it turn a rule off or rewrite history (ADR-0027).
The schema owner is recognised by name, so migrate can run as it."""
from django.conf import settings
from django.core.checks import Error, Tags, Warning, register
from django.db import connections

from .session import connected_role, role_bypasses_rls, role_privilege_problems


@register(Tags.database)
def database_role_is_bound_by_rls(app_configs, databases=None, **kwargs):
    errors = []
    for alias in databases or []:
        if connections[alias].vendor == "postgresql" and role_bypasses_rls(alias):
            errors.append(Error(f"Database role for '{alias}' is a superuser or has BYPASSRLS, so tenant isolation "
                                "would not be enforced.", hint="Connect as a role like wepl_app (see README).",
                                id="tenancy.E001"))
    return errors


@register(Tags.database)
def database_role_owns_nothing(app_configs, databases=None, **kwargs):
    found = []
    for alias in databases or []:
        if connections[alias].vendor != "postgresql":
            continue
        if connected_role(alias) == settings.WEPL_SCHEMA_OWNER:
            found.append(Warning(f"Database role for '{alias}' is the schema owner; only migrate should connect "
                                 "as it.", hint="The application connects as wepl_app (ADR-0027).",
                                 id="tenancy.W001"))
        elif problems := role_privilege_problems(alias):
            found.append(Error(f"Database role for '{alias}' could turn database rules off or rewrite history: "
                               + "; ".join(problems) + ".",
                               hint="Run scripts/database_roles.sql, then migrate as wepl_owner (ADR-0027).",
                               id="tenancy.E002"))
    return found
