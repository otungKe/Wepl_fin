"""Rules the database enforces on its own, so no code path (a bug, a shell
session, a future module) can write an unbalanced or edited ledger."""
from django.db import migrations

from persistence.postgres import append_only

BALANCED = """
CREATE OR REPLACE FUNCTION ledger_entry_must_balance() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    eid bigint;
    n integer;
    unbalanced integer;
BEGIN
    IF TG_TABLE_NAME = 'ledger_journalentry' THEN eid := NEW.id; ELSE eid := NEW.entry_id; END IF;
    SELECT count(*) INTO n FROM ledger_journalline WHERE entry_id = eid;
    IF n < 2 THEN
        RAISE EXCEPTION 'journal entry % has % line(s); at least 2 are required', eid, n
            USING ERRCODE = 'check_violation';
    END IF;
    SELECT count(*) INTO unbalanced FROM (
        SELECT a.currency
        FROM ledger_journalline l JOIN ledger_account a ON a.id = l.account_id
        WHERE l.entry_id = eid
        GROUP BY a.currency
        HAVING sum(CASE WHEN l.side = 'D' THEN l.amount ELSE -l.amount END) <> 0
    ) t;
    IF unbalanced > 0 THEN
        RAISE EXCEPTION 'journal entry % does not balance', eid USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER ledger_line_balanced
    AFTER INSERT ON ledger_journalline DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION ledger_entry_must_balance();
CREATE CONSTRAINT TRIGGER ledger_entry_has_lines
    AFTER INSERT ON ledger_journalentry DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION ledger_entry_must_balance();
"""

UNBALANCED = """
DROP TRIGGER IF EXISTS ledger_line_balanced ON ledger_journalline;
DROP TRIGGER IF EXISTS ledger_entry_has_lines ON ledger_journalentry;
DROP FUNCTION IF EXISTS ledger_entry_must_balance();
"""

operations = [migrations.RunSQL(BALANCED, UNBALANCED)]
for table in ("ledger_journalentry", "ledger_journalline", "ledger_account"):
    operations.append(migrations.RunSQL(*append_only(table)))


class Migration(migrations.Migration):
    dependencies = [("ledger", "0001_initial")]
    operations = operations
