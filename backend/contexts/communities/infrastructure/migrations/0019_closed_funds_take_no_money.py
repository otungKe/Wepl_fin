"""A closed fund takes no money (Communities review of 2026-10-06, C1; ADR-0026).

ADR-0015 relied on "every posting comes through a linked custodian account,
and a closed fund has none". Since one account holds all of a group's funds
(ADR-0023), a fund without an account of its own receives pay-ins quoting its
code, so that no longer held: a pay-in and ``close_fund`` could commit
together and leave a closed fund holding money nothing could pay out.

Now every journal entry reads its fund FOR SHARE and is refused if the fund
is closed. ``close_fund`` locks the fund FOR UPDATE before asking the ledger
whether it holds anything, so the two serialise:
- the entry first: closing waits for it, then finds the money and refuses;
- closing first: the entry waits, then sees the fund closed and is refused.
Entries into the same open fund take shared locks and never wait on each
other. Kept on the communities side of the ledger's tables, like 0013.
"""
from django.db import migrations

FORWARD = """
CREATE FUNCTION communities_entry_into_an_open_fund() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (SELECT status FROM communities_fund WHERE id = NEW.fund_id FOR SHARE) = 'closed' THEN
        RAISE EXCEPTION 'fund % is closed: it takes no money', NEW.fund_id USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER communities_entry_into_an_open_fund BEFORE INSERT ON ledger_journalentry
    FOR EACH ROW EXECUTE FUNCTION communities_entry_into_an_open_fund();
"""

REVERSE = """
DROP TRIGGER IF EXISTS communities_entry_into_an_open_fund ON ledger_journalentry;
DROP FUNCTION IF EXISTS communities_entry_into_an_open_fund();
"""


class Migration(migrations.Migration):
    dependencies = [("communities", "0018_codes_already_used"), ("ledger", "0009_fund_transfers")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
