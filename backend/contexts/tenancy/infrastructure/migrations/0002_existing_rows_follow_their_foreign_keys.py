from django.db import migrations

from persistence.tenancy import revalidate_foreign_keys


class Migration(migrations.Migration):
    """Every foreign key added so far was validated under row-level security
    with no tenant context, so against no rows at all (persistence/tenancy.py).
    Check them again, across every tenant."""

    dependencies = [
        ("tenancy", "0001_initial"),
        ("audit", "0003_tenant"),
        ("notifications", "0005_lookups_that_rls_can_use"),
        ("identity", "0001_initial"),
        ("communities", "0013_linked_rows_keep_their_tenant"),
        ("ledger", "0008_linked_rows_keep_their_tenant"),
        ("governance", "0007_lookups_that_rls_can_use"),
        ("custody", "0006_reconciliation_follows_the_running_balance"),
    ]
    operations = [migrations.RunSQL(revalidate_foreign_keys(), migrations.RunSQL.noop)]
