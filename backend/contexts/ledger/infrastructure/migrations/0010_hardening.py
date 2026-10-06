"""Hardening from the ledger review of 2026-10-06
(docs/architecture/review-ledger-hardening.md):

- one leg of each kind per fund transfer, as a unique index. 0009's pair
  check runs at commit and cannot see another transaction's uncommitted
  legs, so two concurrent postings of one transfer under different keys
  both committed (probed: four legs, a member at -60);
- every entry has a kind and a cause, so it can be traced back;
- a reversal's cause names the entry it reverses, as the domain requires,
  and a fund-transfer leg reverses nothing;
- the nightly check records entries that break the posting rules one by one
  and whether the balance queries agree with its own sums.

The index build and the CHECK validation read every row of the table
directly, not through a query, so row-level security cannot hide rows from
them (unlike a foreign key's validation; see persistence/tenancy.py)."""
import django.db.models.functions.comparison
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ledger", "0009_fund_transfers"),
        ("tenancy", "0002_existing_rows_follow_their_foreign_keys"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="integritycheck",
            name="ledger_check_passed_means_all",
        ),
        migrations.AddField(
            model_name="integritycheck",
            name="broken_entries",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="integritycheck",
            name="queries_agree",
            field=models.BooleanField(default=True),
        ),
        migrations.AddConstraint(
            model_name="integritycheck",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("broken_entries", 0),
                        ("invariant_holds", True),
                        ("passed", True),
                        ("queries_agree", True),
                        ("trial_balance", 0),
                        ("unpaired_transfers", 0),
                    ),
                    models.Q(
                        ("passed", False),
                        models.Q(
                            ("broken_entries", 0),
                            ("invariant_holds", True),
                            ("queries_agree", True),
                            ("trial_balance", 0),
                            ("unpaired_transfers", 0),
                            _negated=True,
                        ),
                    ),
                    _connector="OR",
                ),
                name="ledger_check_passed_means_every_check",
            ),
        ),
        migrations.AddConstraint(
            model_name="journalentry",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("kind__in", ["fund_transfer_in", "fund_transfer_out"])
                ),
                fields=("tenant", "cause_type", "cause_id", "kind"),
                name="ledger_transfer_leg_once",
            ),
        ),
        migrations.AddConstraint(
            model_name="journalentry",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("kind", ""), _negated=True),
                    models.Q(("cause_type", ""), _negated=True),
                    models.Q(("cause_id", ""), _negated=True),
                ),
                name="ledger_entry_has_kind_and_cause",
            ),
        ),
        migrations.AddConstraint(
            model_name="journalentry",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("reverses__isnull", True),
                    models.Q(
                        (
                            "cause_id",
                            django.db.models.functions.comparison.Cast(
                                models.F("reverses"), models.CharField()
                            ),
                        ),
                        ("cause_type", "journal_entry"),
                        models.Q(
                            ("kind__in", ["fund_transfer_in", "fund_transfer_out"]),
                            _negated=True,
                        ),
                    ),
                    _connector="OR",
                ),
                name="ledger_reversal_names_its_original",
            ),
        ),
    ]
