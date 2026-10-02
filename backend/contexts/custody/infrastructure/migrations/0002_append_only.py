from django.db import migrations

from persistence.postgres import append_only


class Migration(migrations.Migration):
    dependencies = [("custody", "0001_initial")]
    operations = [migrations.RunSQL(*append_only(t)) for t in (
        "custody_statementline", "custody_lineresolution", "custody_reconciliationrun")]
