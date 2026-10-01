"""ADR-0017: a line's entry and account, and a reversal's original, are of the
line's or entry's own tenant, as a foreign key PostgreSQL checks for any role
in any mode. (0005's triggers already refuse these; the keys make it
declarative, like every other context's.)"""
from django.db import migrations

from persistence.tenancy import same_tenant, tenant_keyed


class Migration(migrations.Migration):
    dependencies = [("ledger", "0007_indexes_that_rls_can_use")]
    operations = [migrations.RunSQL(*sql) for sql in (
        tenant_keyed("ledger_journalentry"),
        tenant_keyed("ledger_account"),
        same_tenant("ledger_journalline", "entry_id", "ledger_journalentry"),
        same_tenant("ledger_journalline", "account_id", "ledger_account"),
        same_tenant("ledger_journalentry", "reverses_id", "ledger_journalentry"),
    )]
