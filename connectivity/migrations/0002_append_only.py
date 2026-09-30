from django.db import migrations

from platform_core.sql import append_only


class Migration(migrations.Migration):
    dependencies = [("connectivity", "0001_initial")]
    operations = [migrations.RunSQL(*append_only(t)) for t in (
        "connectivity_statementline", "connectivity_lineresolution", "connectivity_reconciliationrun")]
