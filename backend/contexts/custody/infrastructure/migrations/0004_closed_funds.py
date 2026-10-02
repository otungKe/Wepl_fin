"""A fund closes only when no custodian account is linked to it, and a closed
fund takes no new account (fund lifecycle, ADR-0015). Every posting reaches
the ledger through a linked account, so this also ends the fund's postings.

Custody owns this rule, so it lives here, on the side that already depends
on communities. Linking takes a share lock on the fund, and closing updates
the fund row, so the two serialise.
"""
from django.db import migrations

FORWARD = """
CREATE FUNCTION custody_fund_may_close() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status = 'closed' AND OLD.status IS DISTINCT FROM 'closed'
       AND EXISTS (SELECT 1 FROM custody_externalaccount WHERE fund_id = NEW.id) THEN
        RAISE EXCEPTION 'fund % has a linked custodian account; it cannot close', NEW.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER custody_fund_may_close BEFORE UPDATE OF status ON communities_fund
    FOR EACH ROW EXECUTE FUNCTION custody_fund_may_close();

CREATE FUNCTION custody_account_on_open_fund() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (SELECT status FROM communities_fund WHERE id = NEW.fund_id FOR SHARE) IS DISTINCT FROM 'open' THEN
        RAISE EXCEPTION 'fund % is closed', NEW.fund_id USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER custody_account_on_open_fund BEFORE INSERT ON custody_externalaccount
    FOR EACH ROW EXECUTE FUNCTION custody_account_on_open_fund();
"""

REVERSE = """
DROP TRIGGER IF EXISTS custody_account_on_open_fund ON custody_externalaccount;
DROP FUNCTION IF EXISTS custody_account_on_open_fund();
DROP TRIGGER IF EXISTS custody_fund_may_close ON communities_fund;
DROP FUNCTION IF EXISTS custody_fund_may_close();
"""


class Migration(migrations.Migration):
    dependencies = [("custody", "0003_tenant"), ("communities", "0012_fund_lifecycle")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
