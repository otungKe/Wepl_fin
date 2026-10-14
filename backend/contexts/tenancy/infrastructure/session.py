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


# ADR-0027. What the application's role must not be able to do, each as a
# query naming the objects concerned. %(role)s is the role being checked.
_TOO_MUCH = {
    "owns": """
        SELECT c.relname FROM pg_class c
         WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p', 'v', 'm', 'S')
           AND (pg_has_role(%(role)s, c.relowner, 'USAGE') OR pg_has_role(%(role)s, c.relowner, 'SET'))
        UNION ALL
        SELECT p.proname FROM pg_proc p
         WHERE p.pronamespace = 'public'::regnamespace
           AND (pg_has_role(%(role)s, p.proowner, 'USAGE') OR pg_has_role(%(role)s, p.proowner, 'SET'))""",
    "can UPDATE append-only": """
        SELECT DISTINCT t.tgrelid::regclass::text FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid
         WHERE p.proname LIKE '%%\\_append\\_only' AND NOT t.tgisinternal
           AND has_table_privilege(%(role)s, t.tgrelid, 'UPDATE')""",
    "can DELETE, TRUNCATE, REFERENCES or TRIGGER": """
        SELECT c.relname FROM pg_class c
         WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')
           AND has_table_privilege(%(role)s, c.oid, 'DELETE, TRUNCATE, REFERENCES, TRIGGER')""",
    "can CREATE in": """
        SELECT 'schema public' WHERE has_schema_privilege(%(role)s, 'public', 'CREATE')""",
}


def connected_role(alias: str = "default") -> str:
    with connections[alias].cursor() as cur:
        cur.execute("SELECT current_user")
        return cur.fetchone()[0]


def role_privilege_problems(alias: str = "default", role: str | None = None) -> list[str]:
    """What ``role`` (by default the connected one) could do that would let
    it rewrite history or turn a database rule off. Empty for a correctly
    set up application role."""
    role = role or connected_role(alias)
    problems = []
    with connections[alias].cursor() as cur:
        for what, sql in _TOO_MUCH.items():
            cur.execute(sql, {"role": role})
            if names := sorted(r[0] for r in cur.fetchall()):
                problems.append(f"{what} {', '.join(names[:5])}{' …' if len(names) > 5 else ''}")
    return problems
