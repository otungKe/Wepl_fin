from django.db import migrations

from persistence.postgres import append_only


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]
    operations = [migrations.RunSQL(*append_only("audit_auditevent"))]
