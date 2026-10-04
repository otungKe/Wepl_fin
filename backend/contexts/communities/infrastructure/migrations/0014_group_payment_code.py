from django.db import migrations, models

# Five digits, 10000-99999 (90,000 codes), so the whole reference
# ("55555#0712597024", Harry 2026-10-04) can be typed on any phone keypad. A
# collision is refused by the unique key and founding draws again.
NEW_PAYMENT_CODE = """
CREATE FUNCTION communities_new_payment_code() RETURNS varchar LANGUAGE sql VOLATILE AS $$
    SELECT (10000 + floor(random() * 90000))::int::varchar
$$;
"""

CODE_NEVER_CHANGES = """
CREATE FUNCTION communities_payment_code_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.payment_code IS DISTINCT FROM OLD.payment_code THEN
        RAISE EXCEPTION 'a group''s payment code never changes' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER communities_payment_code_fixed BEFORE UPDATE ON communities_group
    FOR EACH ROW EXECUTE FUNCTION communities_payment_code_fixed();
"""


class Migration(migrations.Migration):
    dependencies = [("communities", "0013_linked_rows_keep_their_tenant")]
    operations = [
        migrations.RunSQL(NEW_PAYMENT_CODE, "DROP FUNCTION IF EXISTS communities_new_payment_code();"),
        migrations.AddField(
            model_name="group", name="payment_code",
            field=models.CharField(db_default=models.Func(function="communities_new_payment_code",
                                                          output_field=models.CharField()),
                                   editable=False, max_length=5, unique=True)),
        migrations.RunSQL("ALTER TABLE communities_group ADD CONSTRAINT communities_payment_code_digits "
                          "CHECK (payment_code ~ '^[1-9][0-9]{4}$');",
                          "ALTER TABLE communities_group DROP CONSTRAINT IF EXISTS communities_payment_code_digits;"),
        migrations.RunSQL(CODE_NEVER_CHANGES, """
            DROP TRIGGER IF EXISTS communities_payment_code_fixed ON communities_group;
            DROP FUNCTION IF EXISTS communities_payment_code_fixed();"""),
    ]
