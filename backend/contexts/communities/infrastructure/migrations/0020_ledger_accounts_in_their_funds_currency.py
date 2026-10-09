"""A ledger account is in its fund's currency (ledger hardening review of
2026-10-06, M2).

The ledger balances every entry per currency, but nothing tied an account's
currency to its fund's: a USD account in a KES fund was accepted, and its
money stayed out of every KES balance. Communities owns the fund's currency
and already checks ledger rows against it (0013), so it checks this too.

The check raises only for a fund it can see in the account's tenant. An
account naming another tenant's fund is left to 0013's trigger, so that
refusal keeps its own message. Existing rows are checked across every
tenant first.
"""
from django.db import migrations

from persistence.tenancy import no_existing_violations

FORWARD = """
CREATE FUNCTION communities_account_in_its_funds_currency() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    fund_currency text;
BEGIN
    SELECT currency INTO fund_currency FROM communities_fund WHERE id = NEW.fund_id AND tenant_id = NEW.tenant_id;
    IF FOUND AND fund_currency <> NEW.currency THEN
        RAISE EXCEPTION 'ledger account % is in %, but fund % holds %', NEW.id, NEW.currency, NEW.fund_id,
            fund_currency USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER communities_account_in_its_funds_currency AFTER INSERT ON ledger_account
    FOR EACH ROW EXECUTE FUNCTION communities_account_in_its_funds_currency();
"""

REVERSE = """
DROP TRIGGER IF EXISTS communities_account_in_its_funds_currency ON ledger_account;
DROP FUNCTION IF EXISTS communities_account_in_its_funds_currency();
"""

EXISTING = no_existing_violations("""
    SELECT 1 FROM ledger_account a JOIN communities_fund f ON f.id = a.fund_id AND f.tenant_id = a.tenant_id
     WHERE a.currency <> f.currency""", "ledger accounts in a currency their fund does not hold")


class Migration(migrations.Migration):
    dependencies = [("communities", "0019_closed_funds_take_no_money"), ("ledger", "0010_hardening")]
    operations = [migrations.RunSQL(EXISTING, migrations.RunSQL.noop), migrations.RunSQL(FORWARD, REVERSE)]
