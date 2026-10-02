"""The fund lifecycle (Harry, 2026-10-01; ADR-0015): OPEN, then CLOSED, and
never back; never deleted; renamed only while open. A closed fund's name is
free again, so the any-case name rule covers open funds only.
"""

import django.db.models.functions.text
from django.db import migrations, models


RULES = """
CREATE OR REPLACE FUNCTION communities_fund_rules() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP <> 'UPDATE' THEN
        RAISE EXCEPTION 'funds are never deleted; close one instead' USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.group_id IS DISTINCT FROM OLD.group_id OR NEW.currency IS DISTINCT FROM OLD.currency THEN
        RAISE EXCEPTION 'a fund''s group and currency never change' USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.status = 'closed' AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'fund % is closed: it never reopens or changes; open a new fund', OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS communities_fund_rules ON communities_fund;
CREATE TRIGGER communities_fund_rules BEFORE UPDATE OR DELETE ON communities_fund
    FOR EACH ROW EXECUTE FUNCTION communities_fund_rules();
CREATE TRIGGER communities_fund_rules_truncate BEFORE TRUNCATE ON communities_fund
    FOR EACH STATEMENT EXECUTE FUNCTION communities_fund_rules();
"""

PREVIOUS_RULES = """
DROP TRIGGER IF EXISTS communities_fund_rules_truncate ON communities_fund;
DROP TRIGGER IF EXISTS communities_fund_rules ON communities_fund;
CREATE OR REPLACE FUNCTION communities_fund_rules() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.group_id IS DISTINCT FROM OLD.group_id OR NEW.currency IS DISTINCT FROM OLD.currency THEN
        RAISE EXCEPTION 'a fund''s group and currency never change' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER communities_fund_rules BEFORE UPDATE ON communities_fund
    FOR EACH ROW EXECUTE FUNCTION communities_fund_rules();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("communities", "0011_fund_names_any_case_kes_only"),
        ("tenancy", "0001_initial"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="fund",
            name="community_fund_name_any_case",
        ),
        migrations.AddField(
            model_name="fund",
            name="status",
            field=models.CharField(
                choices=[("open", "open"), ("closed", "closed")],
                db_default="open",
                default="open",
                max_length=10,
            ),
        ),
        migrations.AddConstraint(
            model_name="fund",
            constraint=models.UniqueConstraint(
                models.F("group"),
                django.db.models.functions.text.Lower("name"),
                condition=models.Q(("status", "open")),
                name="community_open_fund_name_any_case",
            ),
        ),
        migrations.RunSQL(RULES, PREVIOUS_RULES),
    ]
