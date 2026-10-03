"""An index the lookup can use under row-level security (ADR-0016)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0004_keys_unique_per_tenant"),
        ("tenancy", "0001_initial"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="outboxevent",
            index=models.Index(fields=["dedupe_key"], name="outbox_dedupe_key"),
        ),
    ]
