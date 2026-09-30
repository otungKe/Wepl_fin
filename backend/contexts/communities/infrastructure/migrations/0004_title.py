"""ADR-0011: a membership carries an optional title (a label), not a role.
The old role becomes the title; what officials could do is carried over as
explicit capability grants by governance 0004, then 0005 drops the role."""
from django.db import migrations, models

COPY = """
SELECT set_config('app.cross_tenant', 'on', true);
UPDATE communities_membership SET title = initcap(role) WHERE role <> 'member';
SELECT set_config('app.cross_tenant', '', true);
"""


class Migration(migrations.Migration):
    dependencies = [("communities", "0003_one_group_per_tenant")]
    operations = [
        migrations.AddField(model_name="membership", name="title",
                            field=models.CharField(blank=True, default="", max_length=60)),
        migrations.RunSQL(COPY, migrations.RunSQL.noop),
    ]
