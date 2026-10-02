from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("communities", "0004_title"), ("governance", "0004_capabilitychange")]
    operations = [migrations.RemoveField(model_name="membership", name="role")]
