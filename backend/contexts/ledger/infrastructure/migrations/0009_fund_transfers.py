"""Money moved between two funds of one group is two entries posted
together (ADR-0024). PostgreSQL holds the pair to the same rule as the
domain (``ledger/domain/transfer.py``), so no code path can commit half a
move or a move that changes who owns the money:

- at commit, every fund-transfer entry has exactly one other half: the same
  cause, the other kind, the same group, another fund;
- the halves mirror: the same owners (members, or the group), the same
  amounts, and the cash leaves and arrives at the same bank account;
- a fund-transfer entry is never reversed; the group moves the money back
  with a new transfer.

The nightly integrity check also counts unpaired halves, in case a rule was
bypassed (a superuser, a restore)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ledger", "0008_linked_rows_keep_their_tenant"),
        ("tenancy", "0002_existing_rows_follow_their_foreign_keys"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="integritycheck",
            name="ledger_check_passed_means_both",
        ),
        migrations.AddField(
            model_name="integritycheck",
            name="unpaired_transfers",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddConstraint(
            model_name="integritycheck",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("invariant_holds", True),
                        ("passed", True),
                        ("trial_balance", 0),
                        ("unpaired_transfers", 0),
                    ),
                    models.Q(
                        ("passed", False),
                        models.Q(
                            ("invariant_holds", True),
                            ("trial_balance", 0),
                            ("unpaired_transfers", 0),
                            _negated=True,
                        ),
                    ),
                    _connector="OR",
                ),
                name="ledger_check_passed_means_all",
            ),
        ),
    ]

PAIR_RULES = """
CREATE FUNCTION ledger_transfer_paired() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    out_id bigint;
    in_id bigint;
    n_out integer;
    n_in integer;
    o record;
    i record;
    outer_tenant text := current_setting('app.tenant_id', true);
BEGIN
    -- Deferred to commit, maybe after the tenant context ended: read as the entry's tenant.
    PERFORM set_config('app.tenant_id', NEW.tenant_id::text, true);
    SELECT count(*) FILTER (WHERE kind = 'fund_transfer_out'), count(*) FILTER (WHERE kind = 'fund_transfer_in'),
           min(id) FILTER (WHERE kind = 'fund_transfer_out'), min(id) FILTER (WHERE kind = 'fund_transfer_in')
      INTO n_out, n_in, out_id, in_id
      FROM ledger_journalentry WHERE cause_type = NEW.cause_type AND cause_id = NEW.cause_id
                                 AND kind IN ('fund_transfer_out', 'fund_transfer_in');
    IF n_out <> 1 OR n_in <> 1 THEN
        RAISE EXCEPTION 'fund transfer %:% must be exactly one entry out and one in (found % and %)',
            NEW.cause_type, NEW.cause_id, n_out, n_in USING ERRCODE = 'check_violation';
    END IF;
    SELECT group_id, fund_id INTO o FROM ledger_journalentry WHERE id = out_id;
    SELECT group_id, fund_id INTO i FROM ledger_journalentry WHERE id = in_id;
    IF o.group_id <> i.group_id OR o.fund_id = i.fund_id THEN
        RAISE EXCEPTION 'fund transfer %:% must move money between two funds of one group',
            NEW.cause_type, NEW.cause_id USING ERRCODE = 'check_violation';
    END IF;
    IF (SELECT count(*) FROM ledger_journalline l JOIN ledger_account a ON a.id = l.account_id
         WHERE l.entry_id = out_id AND a.purpose = 'custody_cash' AND l.side = 'C') <> 1
       OR EXISTS (SELECT 1 FROM ledger_journalline l JOIN ledger_account a ON a.id = l.account_id
                   WHERE l.entry_id = out_id AND NOT (
                       (a.purpose = 'custody_cash' AND l.side = 'C')
                       OR (a.purpose IN ('member_interest', 'retained') AND l.side = 'D'))) THEN
        RAISE EXCEPTION 'fund transfer %:% may only move a member''s or the group''s money out of one bank account',
            NEW.cause_type, NEW.cause_id USING ERRCODE = 'check_violation';
    END IF;
    IF EXISTS (
        (SELECT a.purpose, a.member_id, a.external_account_id, a.currency,
                CASE l.side WHEN 'D' THEN 'C' ELSE 'D' END, l.amount
           FROM ledger_journalline l JOIN ledger_account a ON a.id = l.account_id WHERE l.entry_id = out_id
         EXCEPT ALL
         SELECT a.purpose, a.member_id, a.external_account_id, a.currency, l.side, l.amount
           FROM ledger_journalline l JOIN ledger_account a ON a.id = l.account_id WHERE l.entry_id = in_id)
        UNION ALL
        (SELECT a.purpose, a.member_id, a.external_account_id, a.currency, l.side, l.amount
           FROM ledger_journalline l JOIN ledger_account a ON a.id = l.account_id WHERE l.entry_id = in_id
         EXCEPT ALL
         SELECT a.purpose, a.member_id, a.external_account_id, a.currency,
                CASE l.side WHEN 'D' THEN 'C' ELSE 'D' END, l.amount
           FROM ledger_journalline l JOIN ledger_account a ON a.id = l.account_id WHERE l.entry_id = out_id)) THEN
        RAISE EXCEPTION 'fund transfer %:% must give the destination exactly what the source gives',
            NEW.cause_type, NEW.cause_id USING ERRCODE = 'check_violation';
    END IF;
    PERFORM set_config('app.tenant_id', coalesce(outer_tenant, ''), true);
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER ledger_transfer_paired
    AFTER INSERT ON ledger_journalentry DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW WHEN (NEW.kind IN ('fund_transfer_out', 'fund_transfer_in'))
    EXECUTE FUNCTION ledger_transfer_paired();

CREATE FUNCTION ledger_transfer_not_reversed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (SELECT kind FROM ledger_journalentry WHERE id = NEW.reverses_id) IN ('fund_transfer_out', 'fund_transfer_in') THEN
        RAISE EXCEPTION 'entry % is half of a fund transfer and is never reversed; move the money back instead',
            NEW.reverses_id USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER ledger_transfer_not_reversed BEFORE INSERT ON ledger_journalentry
    FOR EACH ROW WHEN (NEW.reverses_id IS NOT NULL) EXECUTE FUNCTION ledger_transfer_not_reversed();
"""

UNDO_PAIR_RULES = """
DROP TRIGGER IF EXISTS ledger_transfer_not_reversed ON ledger_journalentry;
DROP FUNCTION IF EXISTS ledger_transfer_not_reversed();
DROP TRIGGER IF EXISTS ledger_transfer_paired ON ledger_journalentry;
DROP FUNCTION IF EXISTS ledger_transfer_paired();
"""
Migration.operations.append(migrations.RunSQL(PAIR_RULES, UNDO_PAIR_RULES))
