from django.db import migrations

from platform_core.sql import append_only


class Migration(migrations.Migration):
    dependencies = [("platform_core", "0001_initial")]
    operations = [migrations.RunSQL(*append_only("platform_core_auditevent"))]
