"""ADR-0017: linked rows share a tenant.

- Groups, funds and memberships can be referred to by (id, tenant), so every
  context's keys to them can include the tenant.
- A fund's and a membership's group is of their own tenant, as a key (0009 and
  0010 already check it in triggers).
- The ledger holds plain ids of a group, a fund and a member (ADR-0004: it
  reads no other context). Communities, which already depends on the ledger,
  checks them here, reading only its own tables: the fund is the group's, the
  member is the group's, and both are of the ledger row's tenant.
"""
from django.db import migrations

from persistence.tenancy import no_existing_violations, same_tenant, tenant_keyed

LEDGER_NAMES = """
CREATE OR REPLACE FUNCTION communities_ledger_names_its_own_fund() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    -- Compares tenant explicitly: inside a cross-tenant operation every fund is visible.
    IF NOT EXISTS (SELECT 1 FROM communities_fund
                   WHERE id = NEW.fund_id AND group_id = NEW.group_id AND tenant_id = NEW.tenant_id) THEN
        RAISE EXCEPTION '% % names fund % of group %, which is not its tenant''s', TG_TABLE_NAME, NEW.id,
            NEW.fund_id, NEW.group_id USING ERRCODE = 'foreign_key_violation';
    END IF;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION communities_ledger_names_its_own_member() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM communities_membership
                   WHERE id = NEW.member_id AND group_id = NEW.group_id AND tenant_id = NEW.tenant_id) THEN
        RAISE EXCEPTION 'ledger account % names member %, who is not of its group and tenant', NEW.id,
            NEW.member_id USING ERRCODE = 'foreign_key_violation';
    END IF;
    RETURN NULL;
END $$;

CREATE TRIGGER communities_entry_names_its_own_fund AFTER INSERT ON ledger_journalentry
    FOR EACH ROW EXECUTE FUNCTION communities_ledger_names_its_own_fund();
CREATE TRIGGER communities_account_names_its_own_fund AFTER INSERT ON ledger_account
    FOR EACH ROW EXECUTE FUNCTION communities_ledger_names_its_own_fund();
CREATE TRIGGER communities_account_names_its_own_member AFTER INSERT ON ledger_account
    FOR EACH ROW WHEN (NEW.member_id IS NOT NULL) EXECUTE FUNCTION communities_ledger_names_its_own_member();
"""

LEDGER_NAMES_REVERSE = """
DROP TRIGGER IF EXISTS communities_entry_names_its_own_fund ON ledger_journalentry;
DROP TRIGGER IF EXISTS communities_account_names_its_own_fund ON ledger_account;
DROP TRIGGER IF EXISTS communities_account_names_its_own_member ON ledger_account;
DROP FUNCTION IF EXISTS communities_ledger_names_its_own_fund();
DROP FUNCTION IF EXISTS communities_ledger_names_its_own_member();
"""

EXISTING = no_existing_violations("""
    SELECT 1 FROM ledger_journalentry e WHERE NOT EXISTS (SELECT 1 FROM communities_fund f
        WHERE f.id = e.fund_id AND f.group_id = e.group_id AND f.tenant_id = e.tenant_id)
    UNION ALL
    SELECT 1 FROM ledger_account a WHERE NOT EXISTS (SELECT 1 FROM communities_fund f
        WHERE f.id = a.fund_id AND f.group_id = a.group_id AND f.tenant_id = a.tenant_id)
    UNION ALL
    SELECT 1 FROM ledger_account a WHERE a.member_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM communities_membership m
        WHERE m.id = a.member_id AND m.group_id = a.group_id AND m.tenant_id = a.tenant_id)""",
    "ledger rows naming a fund, group or member outside their tenant")


class Migration(migrations.Migration):
    dependencies = [("communities", "0012_fund_lifecycle"), ("ledger", "0008_linked_rows_keep_their_tenant")]
    operations = [migrations.RunSQL(*sql) for sql in (
        tenant_keyed("communities_group"),
        tenant_keyed("communities_fund"),
        tenant_keyed("communities_membership"),
        same_tenant("communities_fund", "group_id", "communities_group"),
        same_tenant("communities_membership", "group_id", "communities_group"),
        (EXISTING, migrations.RunSQL.noop),
        (LEDGER_NAMES, LEDGER_NAMES_REVERSE),
    )]
