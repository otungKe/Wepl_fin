"""A custodian account can be closed, so its fund can close (ADR-0015).

- ``closed_at`` records when WEPL stopped holding the fund's money at this
  account. It is set once and never changes; a closed account never reopens.
- Nothing else about a linked account ever changes, and an account is never
  deleted: its statement lines and reconciliations point at it.
- A closed account takes no new statement line. Closing locks the account
  row and inserting a line takes a share lock on it, so the two serialise.
- A fund may close once every account linked to it is closed.
"""
from django.db import migrations, models

FORWARD = """
CREATE OR REPLACE FUNCTION custody_fund_may_close() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status = 'closed' AND OLD.status IS DISTINCT FROM 'closed'
       AND EXISTS (SELECT 1 FROM custody_externalaccount WHERE fund_id = NEW.id AND closed_at IS NULL) THEN
        RAISE EXCEPTION 'fund % has a linked custodian account that is still open; it cannot close', NEW.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE FUNCTION custody_account_rules() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'custodian accounts are never deleted' USING ERRCODE = 'restrict_violation';
    END IF;
    IF (NEW.tenant_id, NEW.group_id, NEW.fund_id, NEW.institution, NEW.account_number, NEW.account_name,
        NEW.connector, NEW.currency, NEW.linked_at)
       IS DISTINCT FROM (OLD.tenant_id, OLD.group_id, OLD.fund_id, OLD.institution, OLD.account_number,
                         OLD.account_name, OLD.connector, OLD.currency, OLD.linked_at) THEN
        RAISE EXCEPTION 'a linked custodian account never changes; only closing it is recorded'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.closed_at IS NOT NULL AND NEW.closed_at IS DISTINCT FROM OLD.closed_at THEN
        RAISE EXCEPTION 'a closed custodian account stays closed' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER custody_account_rules BEFORE UPDATE OR DELETE ON custody_externalaccount
    FOR EACH ROW EXECUTE FUNCTION custody_account_rules();

CREATE FUNCTION custody_line_on_open_account() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (SELECT closed_at FROM custody_externalaccount WHERE id = NEW.external_account_id FOR SHARE) IS NOT NULL THEN
        RAISE EXCEPTION 'custodian account % is closed; it takes no new statement line', NEW.external_account_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER custody_line_on_open_account BEFORE INSERT ON custody_statementline
    FOR EACH ROW EXECUTE FUNCTION custody_line_on_open_account();
"""

REVERSE = """
DROP TRIGGER IF EXISTS custody_line_on_open_account ON custody_statementline;
DROP FUNCTION IF EXISTS custody_line_on_open_account();
DROP TRIGGER IF EXISTS custody_account_rules ON custody_externalaccount;
DROP FUNCTION IF EXISTS custody_account_rules();
CREATE OR REPLACE FUNCTION custody_fund_may_close() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status = 'closed' AND OLD.status IS DISTINCT FROM 'closed'
       AND EXISTS (SELECT 1 FROM custody_externalaccount WHERE fund_id = NEW.id) THEN
        RAISE EXCEPTION 'fund % has a linked custodian account; it cannot close', NEW.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$;
"""


class Migration(migrations.Migration):
    dependencies = [("custody", "0006_reconciliation_follows_the_running_balance")]
    operations = [
        migrations.AddField(model_name="externalaccount", name="closed_at",
                            field=models.DateTimeField(editable=False, null=True)),
        migrations.RunSQL(FORWARD, REVERSE),
    ]
