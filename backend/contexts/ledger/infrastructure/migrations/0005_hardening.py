"""Hardening from the ledger infrastructure review of 2026-10-01
(docs/architecture/review-ledger-infrastructure.md). Each rule closes a write
PostgreSQL used to accept, so ADR-0003's promise holds for every code path:

- an entry is sealed when its transaction ends: lines can be added only in
  the transaction that created the entry (Critical 1);
- a line, its entry and its account share one tenant, read under row-level
  security, and the account is in the entry's group and fund (Critical 2,
  Important 5);
- the account key is unique per tenant (Critical 3), and an account's normal
  side follows its purpose; purpose and currency are known values
  (Important 4);
- a reversal reverses an entry of its own tenant, and at commit its lines
  mirror the original's exactly (Important 6).
"""
from django.db import migrations, models

ENTRY_RULES = """
-- An entry is open only in the transaction that created it. The id list is a
-- transaction-local setting: it ends with the transaction, and a rolled-back
-- savepoint takes its additions with it.
CREATE FUNCTION ledger_entry_opened() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    original_tenant bigint;
BEGIN
    IF NEW.reverses_id IS NOT NULL THEN
        SELECT tenant_id INTO original_tenant FROM ledger_journalentry WHERE id = NEW.reverses_id;
        IF NOT FOUND OR original_tenant IS DISTINCT FROM coalesce(NEW.tenant_id, wepl_current_tenant()) THEN
            RAISE EXCEPTION 'entry % reverses an entry outside its tenant', NEW.id
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END IF;
    PERFORM set_config('wepl.ledger_open_entries',
                       coalesce(nullif(current_setting('wepl.ledger_open_entries', true), ''), ',') || NEW.id || ',',
                       true);
    RETURN NULL;
END $$;
CREATE TRIGGER ledger_entry_opened AFTER INSERT ON ledger_journalentry
    FOR EACH ROW EXECUTE FUNCTION ledger_entry_opened();

CREATE FUNCTION ledger_line_consistent() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    line_tenant bigint := coalesce(NEW.tenant_id, wepl_current_tenant());
    e record;
    a record;
BEGIN
    IF position(',' || NEW.entry_id || ',' IN coalesce(current_setting('wepl.ledger_open_entries', true), '')) = 0 THEN
        RAISE EXCEPTION 'journal entry % is already posted; correct it with a reversal, never new lines',
            NEW.entry_id USING ERRCODE = 'restrict_violation';
    END IF;
    -- Read under row-level security: another tenant's entry or account is invisible, so refused.
    SELECT tenant_id, group_id, fund_id INTO e FROM ledger_journalentry WHERE id = NEW.entry_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'line for an unknown journal entry' USING ERRCODE = 'foreign_key_violation';
    END IF;
    SELECT tenant_id, group_id, fund_id INTO a FROM ledger_account WHERE id = NEW.account_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'line for an unknown account' USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF line_tenant IS DISTINCT FROM e.tenant_id OR line_tenant IS DISTINCT FROM a.tenant_id THEN
        RAISE EXCEPTION 'a line, its entry and its account belong to one tenant'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF (a.group_id, a.fund_id) IS DISTINCT FROM (e.group_id, e.fund_id) THEN
        RAISE EXCEPTION 'every posting must belong to the entry''s group and fund'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER ledger_line_consistent BEFORE INSERT ON ledger_journalline
    FOR EACH ROW EXECUTE FUNCTION ledger_line_consistent();
"""

UNDO_ENTRY_RULES = """
DROP TRIGGER IF EXISTS ledger_line_consistent ON ledger_journalline;
DROP FUNCTION IF EXISTS ledger_line_consistent();
DROP TRIGGER IF EXISTS ledger_entry_opened ON ledger_journalentry;
DROP FUNCTION IF EXISTS ledger_entry_opened();
"""

# The commit-time check (0002, made tenant-aware in 0003) now also requires a
# reversal's lines to mirror its original's: same accounts and amounts,
# opposite sides, nothing more and nothing less.
BALANCE_AND_MIRROR = """
CREATE OR REPLACE FUNCTION ledger_entry_must_balance() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    eid bigint;
    n integer;
    unbalanced integer;
    reversed bigint;
    outer_tenant text := current_setting('app.tenant_id', true);
BEGIN
    IF TG_TABLE_NAME = 'ledger_journalentry' THEN eid := NEW.id; ELSE eid := NEW.entry_id; END IF;
    PERFORM set_config('app.tenant_id', NEW.tenant_id::text, true);
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
    IF TG_TABLE_NAME = 'ledger_journalentry' THEN
        reversed := NEW.reverses_id;
        IF reversed IS NOT NULL AND EXISTS (
            (SELECT account_id, side, amount FROM ledger_journalline WHERE entry_id = eid
             EXCEPT ALL
             SELECT account_id, CASE side WHEN 'D' THEN 'C' ELSE 'D' END, amount
             FROM ledger_journalline WHERE entry_id = reversed)
            UNION ALL
            (SELECT account_id, CASE side WHEN 'D' THEN 'C' ELSE 'D' END, amount
             FROM ledger_journalline WHERE entry_id = reversed
             EXCEPT ALL
             SELECT account_id, side, amount FROM ledger_journalline WHERE entry_id = eid)) THEN
            RAISE EXCEPTION 'journal entry % does not mirror the entry % it reverses', eid, reversed
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    -- On a refusal above, the transaction aborts and the setting goes with it.
    PERFORM set_config('app.tenant_id', coalesce(outer_tenant, ''), true);
    RETURN NULL;
END $$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("ledger", "0004_keys_unique_per_tenant"),
        ("tenancy", "0001_initial"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="account",
            name="ledger_account_unique_key",
        ),
        migrations.AddConstraint(
            model_name="account",
            constraint=models.UniqueConstraint(
                fields=(
                    "tenant",
                    "fund_id",
                    "purpose",
                    "member_id",
                    "external_account_id",
                    "currency",
                ),
                name="ledger_account_unique_key",
                nulls_distinct=False,
            ),
        ),
        migrations.AddConstraint(
            model_name="account",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "purpose__in",
                        [
                            "custody_cash",
                            "member_interest",
                            "unattributed_in",
                            "unexplained_out",
                            "retained",
                        ],
                    )
                ),
                name="ledger_account_purpose_known",
            ),
        ),
        migrations.AddConstraint(
            model_name="account",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("normal_side", "D"),
                        ("purpose__in", ["custody_cash", "unexplained_out"]),
                    ),
                    models.Q(
                        models.Q(
                            ("purpose__in", ["custody_cash", "unexplained_out"]),
                            _negated=True,
                        ),
                        ("normal_side", "C"),
                    ),
                    _connector="OR",
                ),
                name="ledger_account_normal_side_follows_purpose",
            ),
        ),
        migrations.AddConstraint(
            model_name="account",
            constraint=models.CheckConstraint(
                condition=models.Q(("currency__regex", "^[A-Z]{3}$")),
                name="ledger_account_currency_code",
            ),
        ),
        migrations.RunSQL(ENTRY_RULES, UNDO_ENTRY_RULES),
        migrations.RunSQL(BALANCE_AND_MIRROR, migrations.RunSQL.noop),
    ]
