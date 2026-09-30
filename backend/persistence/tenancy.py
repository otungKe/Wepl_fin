"""The database side of tenancy (ADR-0009), used by every context's
migrations and models. The policy functions are created by the tenancy
context's first migration."""
from django.db import models

FUNCTIONS = """
CREATE OR REPLACE FUNCTION wepl_current_tenant() RETURNS bigint LANGUAGE sql STABLE AS $$
    SELECT NULLIF(current_setting('app.tenant_id', true), '')::bigint
$$;
CREATE OR REPLACE FUNCTION wepl_cross_tenant() RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT coalesce(current_setting('app.cross_tenant', true), '') = 'on'
$$;
CREATE OR REPLACE FUNCTION wepl_stamp_tenant() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.tenant_id IS NULL THEN
        NEW.tenant_id := wepl_current_tenant();
    END IF;
    RETURN NEW;
END $$;
"""
DROP_FUNCTIONS = """
DROP FUNCTION IF EXISTS wepl_stamp_tenant();
DROP FUNCTION IF EXISTS wepl_cross_tenant();
DROP FUNCTION IF EXISTS wepl_current_tenant();
"""


def tenant_column():
    """The tenant a row belongs to. Nullable here only so the database can stamp
    it from the tenant context on insert; the migration makes it NOT NULL."""
    return models.ForeignKey("tenancy.Tenant", on_delete=models.PROTECT, null=True, blank=True, editable=False,
                             related_name="+")


def tenant_scoped(table: str, *, system_rows: bool = False) -> tuple[str, str]:
    """(forward, reverse) SQL: stamp tenant_id from context, and force
    row-level security so a row is visible and writable only inside its own
    tenant's context or a declared cross-tenant operation. Without a context
    nothing is visible and nothing can be written: the policy fails closed.
    ``system_rows`` allows tenant-less rows, visible only cross-tenant."""
    rule = "(tenant_id = wepl_current_tenant() OR wepl_cross_tenant())"
    forward = f"""
    {'' if system_rows else f'ALTER TABLE {table} ALTER COLUMN tenant_id SET NOT NULL;'}
    CREATE TRIGGER {table}_stamp_tenant BEFORE INSERT ON {table}
        FOR EACH ROW EXECUTE FUNCTION wepl_stamp_tenant();
    ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
    ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
    CREATE POLICY {table}_tenant_isolation ON {table} USING {rule} WITH CHECK {rule};
    """
    reverse = f"""
    DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};
    ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;
    ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
    DROP TRIGGER IF EXISTS {table}_stamp_tenant ON {table};
    {'' if system_rows else f'ALTER TABLE {table} ALTER COLUMN tenant_id DROP NOT NULL;'}
    """
    return forward, reverse
