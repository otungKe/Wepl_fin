"""One bank account holds all of a group's funds (ADR-0023).

A ledger cash account names the custodian account its fund's money is held
at. That account was required to be linked to the same fund; now it must be
the same group's (and tenant's): each of the group's funds has its own cash
at the group's one account. ``ExternalAccount.fund`` is the default fund.
"""
from django.db import migrations

GROUP_ACCOUNT = """
CREATE OR REPLACE FUNCTION custody_cash_names_its_own_account() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    -- Compares tenant explicitly: inside a cross-tenant operation every row is visible.
    IF NOT EXISTS (SELECT 1 FROM custody_externalaccount
                   WHERE id = NEW.external_account_id AND group_id = NEW.group_id AND tenant_id = NEW.tenant_id) THEN
        RAISE EXCEPTION 'ledger account % names custodian account %, which is not of its group and tenant',
            NEW.id, NEW.external_account_id USING ERRCODE = 'foreign_key_violation';
    END IF;
    RETURN NULL;
END $$;
"""

FUND_ACCOUNT = """
CREATE OR REPLACE FUNCTION custody_cash_names_its_own_account() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM custody_externalaccount
                   WHERE id = NEW.external_account_id AND fund_id = NEW.fund_id AND tenant_id = NEW.tenant_id) THEN
        RAISE EXCEPTION 'ledger account % names custodian account %, which is not of its fund and tenant',
            NEW.id, NEW.external_account_id USING ERRCODE = 'foreign_key_violation';
    END IF;
    RETURN NULL;
END $$;
"""


class Migration(migrations.Migration):
    dependencies = [("custody", "0007_closing_an_account")]
    operations = [migrations.RunSQL(GROUP_ACCOUNT, FUND_ACCOUNT)]
