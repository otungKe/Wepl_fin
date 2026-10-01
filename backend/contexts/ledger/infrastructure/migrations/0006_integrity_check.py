"""The nightly integrity check's record: tenant-scoped like the books it
looks at, and append-only, so a failed check can never be quietly removed."""
import django.db.models.deletion
from django.db import migrations, models

from persistence.postgres import append_only
from persistence.tenancy import tenant_scoped


class Migration(migrations.Migration):

    dependencies = [
        ("ledger", "0005_hardening"),
        ("tenancy", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="IntegrityCheck",
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
                ("fund_id", models.BigIntegerField()),
                ("currency", models.CharField(max_length=3)),
                ("trial_balance", models.DecimalField(decimal_places=2, max_digits=18)),
                ("cash", models.DecimalField(decimal_places=2, max_digits=18)),
                (
                    "member_interests",
                    models.DecimalField(decimal_places=2, max_digits=18),
                ),
                ("unattributed", models.DecimalField(decimal_places=2, max_digits=18)),
                ("retained", models.DecimalField(decimal_places=2, max_digits=18)),
                (
                    "unexplained_out",
                    models.DecimalField(decimal_places=2, max_digits=18),
                ),
                ("invariant_holds", models.BooleanField()),
                ("passed", models.BooleanField()),
                ("lines", models.PositiveBigIntegerField()),
                ("checked_at", models.DateTimeField(auto_now_add=True)),
                (
                    "operation_id",
                    models.CharField(blank=True, default="", max_length=64),
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
                        fields=["fund_id", "id"], name="ledger_inte_fund_id_e58618_idx"
                    )
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(
                                ("invariant_holds", True),
                                ("passed", True),
                                ("trial_balance", 0),
                            ),
                            models.Q(
                                ("passed", False),
                                models.Q(
                                    ("invariant_holds", True),
                                    ("trial_balance", 0),
                                    _negated=True,
                                ),
                            ),
                            _connector="OR",
                        ),
                        name="ledger_check_passed_means_both",
                    )
                ],
            },
        ),
    ]

Migration.operations += [migrations.RunSQL(*tenant_scoped("ledger_integritycheck")),
                         migrations.RunSQL(*append_only("ledger_integritycheck"))]
