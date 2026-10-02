"""ADR-0017: linked rows share a tenant.

- Every custody key to a group, fund, member, mandate, custodian account or
  statement line includes the tenant, so PostgreSQL checks it for any role in
  any mode.
- Three links are plain ids, so that the ledger and governance read no other
  context (ADR-0004). Custody already depends on both, so it checks them,
  each against the referenced row's tenant:
  - a ledger cash account names a custodian account of its own fund;
  - a line's resolution names a journal entry of its own tenant;
  - an executed mandate names a statement line of its own tenant.
"""
from django.db import migrations

from persistence.tenancy import no_existing_violations, same_tenant, tenant_keyed

GROUP, FUND, MEMBERSHIP = "communities_group", "communities_fund", "communities_membership"

PLAIN_IDS = """
CREATE OR REPLACE FUNCTION custody_cash_names_its_own_account() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    -- Compares tenant explicitly: inside a cross-tenant operation every row is visible.
    IF NOT EXISTS (SELECT 1 FROM custody_externalaccount
                   WHERE id = NEW.external_account_id AND fund_id = NEW.fund_id AND tenant_id = NEW.tenant_id) THEN
        RAISE EXCEPTION 'ledger account % names custodian account %, which is not of its fund and tenant',
            NEW.id, NEW.external_account_id USING ERRCODE = 'foreign_key_violation';
    END IF;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION custody_resolution_names_its_own_entry() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM ledger_journalentry
                   WHERE id = NEW.journal_entry_id AND tenant_id = NEW.tenant_id) THEN
        RAISE EXCEPTION 'line resolution % names journal entry %, which is not of its tenant', NEW.id,
            NEW.journal_entry_id USING ERRCODE = 'foreign_key_violation';
    END IF;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION custody_mandate_names_its_own_line() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM custody_statementline
                   WHERE id = NEW.executed_by_line_id AND tenant_id = NEW.tenant_id) THEN
        RAISE EXCEPTION 'mandate % names statement line %, which is not of its tenant', NEW.id,
            NEW.executed_by_line_id USING ERRCODE = 'foreign_key_violation';
    END IF;
    RETURN NULL;
END $$;

CREATE TRIGGER custody_cash_names_its_own_account AFTER INSERT ON ledger_account
    FOR EACH ROW WHEN (NEW.external_account_id IS NOT NULL) EXECUTE FUNCTION custody_cash_names_its_own_account();
CREATE TRIGGER custody_resolution_names_its_own_entry AFTER INSERT ON custody_lineresolution
    FOR EACH ROW EXECUTE FUNCTION custody_resolution_names_its_own_entry();
CREATE TRIGGER custody_mandate_names_its_own_line AFTER INSERT OR UPDATE OF executed_by_line_id ON governance_mandate
    FOR EACH ROW WHEN (NEW.executed_by_line_id IS NOT NULL) EXECUTE FUNCTION custody_mandate_names_its_own_line();
"""

PLAIN_IDS_REVERSE = """
DROP TRIGGER IF EXISTS custody_cash_names_its_own_account ON ledger_account;
DROP TRIGGER IF EXISTS custody_resolution_names_its_own_entry ON custody_lineresolution;
DROP TRIGGER IF EXISTS custody_mandate_names_its_own_line ON governance_mandate;
DROP FUNCTION IF EXISTS custody_cash_names_its_own_account();
DROP FUNCTION IF EXISTS custody_resolution_names_its_own_entry();
DROP FUNCTION IF EXISTS custody_mandate_names_its_own_line();
"""

EXISTING = no_existing_violations("""
    SELECT 1 FROM ledger_account a WHERE a.external_account_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM custody_externalaccount x
        WHERE x.id = a.external_account_id AND x.fund_id = a.fund_id AND x.tenant_id = a.tenant_id)
    UNION ALL
    SELECT 1 FROM custody_lineresolution r WHERE NOT EXISTS (
        SELECT 1 FROM ledger_journalentry e WHERE e.id = r.journal_entry_id AND e.tenant_id = r.tenant_id)
    UNION ALL
    SELECT 1 FROM governance_mandate m WHERE m.executed_by_line_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM custody_statementline l WHERE l.id = m.executed_by_line_id AND l.tenant_id = m.tenant_id)""",
    "rows naming a custodian account, journal entry or statement line outside their tenant")


class Migration(migrations.Migration):
    dependencies = [("custody", "0004_closed_funds"), ("governance", "0006_linked_rows_keep_their_tenant"),
                    ("ledger", "0008_linked_rows_keep_their_tenant")]
    operations = [migrations.RunSQL(*sql) for sql in (
        tenant_keyed("custody_externalaccount"),
        tenant_keyed("custody_statementline"),
        same_tenant("custody_externalaccount", "group_id", GROUP),
        same_tenant("custody_externalaccount", "fund_id", FUND),
        same_tenant("custody_statementline", "external_account_id", "custody_externalaccount"),
        same_tenant("custody_lineresolution", "line_id", "custody_statementline"),
        same_tenant("custody_lineresolution", "membership_id", MEMBERSHIP),
        same_tenant("custody_lineresolution", "mandate_id", "governance_mandate"),
        same_tenant("custody_payermapping", "group_id", GROUP),
        same_tenant("custody_payermapping", "membership_id", MEMBERSHIP),
        same_tenant("custody_alert", "group_id", GROUP),
        same_tenant("custody_alert", "line_id", "custody_statementline"),
        same_tenant("custody_reconciliationrun", "external_account_id", "custody_externalaccount"),
        (EXISTING, migrations.RunSQL.noop),
        (PLAIN_IDS, PLAIN_IDS_REVERSE),
    )]
