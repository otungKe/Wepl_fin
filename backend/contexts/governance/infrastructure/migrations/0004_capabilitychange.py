"""ADR-0011: what a member may do is an explicit, append-only capability grant,
not their title. Every former official (chair, treasurer, secretary) is granted
exactly what the role let them do, so no authority is gained or lost."""

import django.db.models.deletion
from django.db import migrations, models

from persistence.postgres import append_only
from persistence.tenancy import tenant_scoped


class Migration(migrations.Migration):

    dependencies = [
        ("communities", "0004_title"),
        ("governance", "0003_tenant"),
        ("tenancy", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="CapabilityChange",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "capability",
                    models.CharField(
                        choices=[
                            ("approve_payout", "approve_payout"),
                            ("cancel_payout", "cancel_payout"),
                            ("correct_records", "correct_records"),
                        ],
                        max_length=30,
                    ),
                ),
                ("granted", models.BooleanField()),
                ("changed_by", models.CharField(max_length=120)),
                ("changed_at", models.DateTimeField(auto_now_add=True)),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="communities.group",
                    ),
                ),
                (
                    "membership",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="communities.membership",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="tenancy.tenant",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["membership", "id"],
                        name="governance__members_8ec56b_idx",
                    )
                ],
            },
        ),
    ]

CARRY_OVER = """
SELECT set_config('app.cross_tenant', 'on', true);
INSERT INTO governance_capabilitychange (tenant_id, group_id, membership_id, capability, granted, changed_by, changed_at)
SELECT m.tenant_id, m.group_id, m.id, c.capability, true, 'migration: former official (ADR-0011)', now()
FROM communities_membership m
CROSS JOIN (VALUES ('approve_payout'), ('cancel_payout'), ('correct_records')) AS c(capability)
WHERE m.role IN ('chair', 'treasurer', 'secretary') AND m.status = 'active'
ORDER BY m.id, c.capability;
SELECT set_config('app.cross_tenant', '', true);
"""

Migration.operations += [
    migrations.RunSQL(*tenant_scoped("governance_capabilitychange")),
    migrations.RunSQL(*append_only("governance_capabilitychange")),
    migrations.RunSQL(CARRY_OVER, migrations.RunSQL.noop),
]
