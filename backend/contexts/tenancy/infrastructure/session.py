"""The database half of tenant context: transaction-local settings that the
row-level security policies read. Nothing outside this module sets them."""
from django.db import connection, connections


def _set(name: str, value: str) -> None:
    with connection.cursor() as cur:
        cur.execute("SELECT set_config(%s, %s, true)", [name, value])


def set_tenant(tenant_id: int | None) -> None:
    _set("app.tenant_id", "" if tenant_id is None else str(int(tenant_id)))


def set_cross_tenant(on: bool) -> None:
    _set("app.cross_tenant", "on" if on else "")


def database_tenant() -> int | None:
    with connection.cursor() as cur:
        cur.execute("SELECT wepl_current_tenant()")
        return cur.fetchone()[0]


def role_bypasses_rls(alias: str = "default") -> bool:
    """True if the connected role would ignore row-level security."""
    with connections[alias].cursor() as cur:
        cur.execute("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
        return cur.fetchone()[0]
