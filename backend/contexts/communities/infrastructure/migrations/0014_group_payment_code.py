from django.db import migrations, models

# Seven digits: six random (100000-999999, 900,000 codes), then a Damm check
# digit, so a mistyped digit or two swapped neighbours never name a group
# (ADR-0018). Members quote it before their mobile number:
# "1234566 0712597024". A collision is refused by the unique key and founding
# draws again. The table matches contexts/shared_kernel/check_digit.py.
NEW_PAYMENT_CODE = """
CREATE FUNCTION communities_damm(digits text) RETURNS int LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE
    t constant text := '0317598642709215486342068713591750983426612304597836742095815869720134894536201794386172052581436790';
    i int := 0;
BEGIN
    FOR k IN 1..length(digits) LOOP
        i := substr(t, i * 10 + substr(digits, k, 1)::int + 1, 1)::int;
    END LOOP;
    RETURN i;
END $$;
CREATE FUNCTION communities_new_payment_code() RETURNS varchar LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    base text := (100000 + floor(random() * 900000))::int::text;
BEGIN
    RETURN base || communities_damm(base)::text;
END $$;
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
        migrations.RunSQL(NEW_PAYMENT_CODE, """
            DROP FUNCTION IF EXISTS communities_new_payment_code();
            DROP FUNCTION IF EXISTS communities_damm(text);"""),
        migrations.AddField(
            model_name="group", name="payment_code",
            field=models.CharField(db_default=models.Func(function="communities_new_payment_code",
                                                          output_field=models.CharField()),
                                   editable=False, max_length=7, unique=True)),
        migrations.RunSQL("ALTER TABLE communities_group ADD CONSTRAINT communities_payment_code_digits "
                          "CHECK (payment_code ~ '^[1-9][0-9]{6}$' "
                          "AND communities_damm(payment_code) = 0);",
                          "ALTER TABLE communities_group DROP CONSTRAINT IF EXISTS communities_payment_code_digits;"),
        migrations.RunSQL(CODE_NEVER_CHANGES, """
            DROP TRIGGER IF EXISTS communities_payment_code_fixed ON communities_group;
            DROP FUNCTION IF EXISTS communities_payment_code_fixed();"""),
    ]
