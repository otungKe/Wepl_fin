"""Harry, 2026-10-01 (docs/architecture/review-funds-module.md, C1, D3):

- fund names are unique per group regardless of case: "Savings" and
  "savings" are one fund to the members who name it;
- funds are held in KES only for the pilot. Allowing another currency is an
  ADR first, then a migration widening this check.
"""

import django.db.models.functions.text
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("communities", "0010_fund_integrity"),
        ("tenancy", "0001_initial"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="fund",
            name="community_fund_name",
        ),
        migrations.AddConstraint(
            model_name="fund",
            constraint=models.UniqueConstraint(
                models.F("group"),
                django.db.models.functions.text.Lower("name"),
                name="community_fund_name_any_case",
            ),
        ),
        migrations.AddConstraint(
            model_name="fund",
            constraint=models.CheckConstraint(
                condition=models.Q(("currency__in", ("KES",))),
                name="community_fund_currency",
            ),
        ),
    ]
