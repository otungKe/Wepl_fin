from django.db import migrations, models

# Five characters from the mandate alphabet (no 0/O, 1/I), so a code survives
# being read out and retyped: 32^5 = 33.5 million codes. A collision is
# refused by the unique key and founding draws again.
NEW_PAYMENT_CODE = """
CREATE FUNCTION communities_new_payment_code() RETURNS varchar LANGUAGE sql VOLATILE AS $$
    SELECT string_agg(substr('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', 1 + floor(random() * 32)::int, 1), '')
    FROM generate_series(1, 5)
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
        migrations.RunSQL(CODE_NEVER_CHANGES, """
            DROP TRIGGER IF EXISTS communities_payment_code_fixed ON communities_group;
            DROP FUNCTION IF EXISTS communities_payment_code_fixed();"""),
    ]
