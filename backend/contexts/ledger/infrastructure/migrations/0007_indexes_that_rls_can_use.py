"""Indexes the ledger's reads can use under row-level security (ADR-0016).
Plain CREATE INDEX: at pilot size it takes moments; on a large table use
CONCURRENTLY in a separate, non-atomic migration."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ledger", "0006_integrity_check"),
        ("tenancy", "0001_initial"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="account",
            index=models.Index(fields=["fund_id"], name="ledger_account_fund"),
        ),
        migrations.AddIndex(
            model_name="journalentry",
            index=models.Index(fields=["idempotency_key"], name="ledger_entry_key"),
        ),
    ]
