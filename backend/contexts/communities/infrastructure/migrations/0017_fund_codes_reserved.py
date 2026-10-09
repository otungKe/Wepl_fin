"""A fund code means one fund of its group for good (Harry, 2026-10-06;
ADR-0026; Communities review C2).

- ``communities_fundcode`` keeps every code each fund has had. When a fund
  takes a code, PostgreSQL records it there; a code another fund of the group
  ever held is refused, so a payer quoting an old code can never pay into a
  different fund: not after a change of code, not after the fund closes. The
  fund that held it may take it back. The table is append-only.
- Codes are three to six letters (Harry, 2026-10-06): fewer ordinary words
  a payer types are read as a fund code.
- The codes already used are reserved by 0018.
"""
import django.db.models.deletion
import django.db.models.functions.datetime
from django.db import migrations, models

from persistence.tenancy import same_tenant, tenant_scoped

RESERVE = """
CREATE FUNCTION communities_fund_code_reserved() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    holder bigint;
BEGIN
    IF NEW.code IS NULL THEN
        RETURN NULL;
    END IF;
    INSERT INTO communities_fundcode (tenant_id, group_id, code, fund_id)
        VALUES (NEW.tenant_id, NEW.group_id, NEW.code, NEW.id)
        ON CONFLICT (group_id, code) DO NOTHING;
    SELECT fund_id INTO holder FROM communities_fundcode WHERE group_id = NEW.group_id AND code = NEW.code;
    IF holder IS DISTINCT FROM NEW.id THEN
        RAISE EXCEPTION 'fund code % belongs to fund % of this group for good', NEW.code, holder
            USING ERRCODE = 'unique_violation', CONSTRAINT = 'community_fund_code_reserved';
    END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER communities_fund_code_reserved AFTER INSERT OR UPDATE OF code ON communities_fund
    FOR EACH ROW EXECUTE FUNCTION communities_fund_code_reserved();

CREATE FUNCTION communities_fundcode_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'a fund code, once used, stays its fund''s: % is not allowed', TG_OP
        USING ERRCODE = 'restrict_violation';
END $$;
CREATE TRIGGER communities_fundcode_append_only BEFORE UPDATE OR DELETE ON communities_fundcode
    FOR EACH ROW EXECUTE FUNCTION communities_fundcode_append_only();
CREATE TRIGGER communities_fundcode_append_only_truncate BEFORE TRUNCATE ON communities_fundcode
    FOR EACH STATEMENT EXECUTE FUNCTION communities_fundcode_append_only();
"""

UNDO_RESERVE = """
DROP TRIGGER IF EXISTS communities_fundcode_append_only_truncate ON communities_fundcode;
DROP TRIGGER IF EXISTS communities_fundcode_append_only ON communities_fundcode;
DROP FUNCTION IF EXISTS communities_fundcode_append_only();
DROP TRIGGER IF EXISTS communities_fund_code_reserved ON communities_fund;
DROP FUNCTION IF EXISTS communities_fund_code_reserved();
"""



class Migration(migrations.Migration):

    dependencies = [
        ("communities", "0016_statuses_and_spells_checked"),
        ("tenancy", "0002_existing_rows_follow_their_foreign_keys"),
    ]

    operations = [
        migrations.CreateModel(
            name="FundCode",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=6)),
                ("first_used_at", models.DateTimeField(db_default=django.db.models.functions.datetime.Now())),
                ("fund", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+",
                                           to="communities.fund")),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+",
                                            to="communities.group")),
                ("tenant", models.ForeignKey(blank=True, editable=False, null=True,
                                             on_delete=django.db.models.deletion.PROTECT, related_name="+",
                                             to="tenancy.tenant")),
            ],
        ),
        migrations.AddConstraint(
            model_name="fundcode",
            constraint=models.UniqueConstraint(fields=("group", "code"), name="community_fund_code_reserved"),
        ),
        migrations.RemoveConstraint(model_name="fund", name="community_fund_code_letters"),
        migrations.AddConstraint(
            model_name="fund",
            constraint=models.CheckConstraint(
                condition=models.Q(("code__isnull", True), ("code__regex", "^[A-Z]{3,6}$"), _connector="OR"),
                name="community_fund_code_letters"),
        ),
    ] + [migrations.RunSQL(*sql) for sql in (
        tenant_scoped("communities_fundcode"),
        same_tenant("communities_fundcode", "group_id", "communities_group"),
        same_tenant("communities_fundcode", "fund_id", "communities_fund"),
        (RESERVE, UNDO_RESERVE),
    )]
