"""The sign-in log cannot be edited or deleted, and an operator is never
deleted: the log and the audit trail name them (ADR-0021)."""
from django.db import migrations

from persistence.postgres import append_only

KEEP_OPERATORS = """
CREATE FUNCTION operators_never_deleted() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'operators are deactivated, never deleted' USING ERRCODE = 'restrict_violation';
END $$;
CREATE TRIGGER operators_never_deleted BEFORE DELETE ON operators_operator
    FOR EACH ROW EXECUTE FUNCTION operators_never_deleted();
"""

UNDO_KEEP_OPERATORS = """
DROP TRIGGER IF EXISTS operators_never_deleted ON operators_operator;
DROP FUNCTION IF EXISTS operators_never_deleted();
"""


class Migration(migrations.Migration):
    dependencies = [("operators", "0001_initial")]
    operations = [migrations.RunSQL(*append_only("operators_operatorevent")),
                  migrations.RunSQL(KEEP_OPERATORS, UNDO_KEEP_OPERATORS)]
