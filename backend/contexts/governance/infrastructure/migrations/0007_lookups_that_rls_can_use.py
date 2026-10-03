"""An index the lookup can use under row-level security (ADR-0016)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("communities", "0013_linked_rows_keep_their_tenant"),
        ("governance", "0006_linked_rows_keep_their_tenant"),
        ("tenancy", "0001_initial"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="proposal",
            index=models.Index(fields=["request_key"], name="gov_proposal_request_key"),
        ),
    ]
