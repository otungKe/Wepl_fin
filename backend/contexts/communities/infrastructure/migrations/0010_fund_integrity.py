"""Review of the fund module (docs/architecture/review-funds-module.md, B1, B2).

- A fund belongs to its group's tenant. PostgreSQL's foreign-key check does
  not apply row-level security, so nothing stopped a fund naming another
  tenant's group. This trigger reads the group under row-level security (a
  foreign group is invisible, so refused) and refuses a tenant other than the
  group's. It fires before the tenant stamp (triggers fire by name), so it
  compares the tenant the row will get: the one given, else the current one.
- A fund's group and currency never change. The ledger keys the fund's
  accounts by currency and custody copies it when an account is linked; a
  fund moved to another group would carry its proposals and books with it.
"""
from django.db import migrations

FORWARD = """
CREATE FUNCTION communities_fund_in_its_groups_tenant() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    group_tenant bigint;
BEGIN
    SELECT tenant_id INTO group_tenant FROM communities_group WHERE id = NEW.group_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'fund for an unknown group' USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF coalesce(NEW.tenant_id, wepl_current_tenant()) IS DISTINCT FROM group_tenant THEN
        RAISE EXCEPTION 'a fund belongs to its group''s tenant (%)', group_tenant
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER communities_fund_in_its_groups_tenant BEFORE INSERT ON communities_fund
    FOR EACH ROW EXECUTE FUNCTION communities_fund_in_its_groups_tenant();

CREATE FUNCTION communities_fund_rules() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.group_id IS DISTINCT FROM OLD.group_id OR NEW.currency IS DISTINCT FROM OLD.currency THEN
        RAISE EXCEPTION 'a fund''s group and currency never change' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER communities_fund_rules BEFORE UPDATE ON communities_fund
    FOR EACH ROW EXECUTE FUNCTION communities_fund_rules();
"""

REVERSE = """
DROP TRIGGER IF EXISTS communities_fund_rules ON communities_fund;
DROP FUNCTION IF EXISTS communities_fund_rules();
DROP TRIGGER IF EXISTS communities_fund_in_its_groups_tenant ON communities_fund;
DROP FUNCTION IF EXISTS communities_fund_in_its_groups_tenant();
"""


class Migration(migrations.Migration):
    dependencies = [("communities", "0009_membership_in_its_groups_tenant")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
