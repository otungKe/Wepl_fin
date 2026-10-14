"""ADR-0027: the application does not own its tables.

The schema owner (wepl_owner) runs this migration and every one after it.
The application's role gets only what it needs, through wepl_runtime:

- SELECT and INSERT on every table, UPDATE where a row's state may change;
- no UPDATE on an append-only table, so the privilege and the trigger are
  two independent locks on history;
- never DELETE, TRUNCATE, REFERENCES or TRIGGER, and no ownership, so it
  cannot turn a trigger, a policy or forced row-level security off.

Tables created later get the same through default privileges, and
``persistence.postgres.append_only`` takes UPDATE away again. The roles
themselves come from scripts/database_roles.sql.
"""
from django.db import migrations

GRANTS = r"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'wepl_runtime') THEN
        RAISE EXCEPTION 'the role wepl_runtime does not exist: run scripts/database_roles.sql first (ADR-0027)';
    END IF;
    IF (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
        RAISE EXCEPTION 'migrations run as the schema owner wepl_owner, not as a superuser (ADR-0027)';
    END IF;
    IF pg_has_role(current_user, 'wepl_runtime', 'MEMBER') THEN
        RAISE EXCEPTION 'migrations run as the schema owner wepl_owner, not as the application''s role (ADR-0027)';
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO wepl_runtime;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO wepl_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO wepl_runtime;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO wepl_runtime;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO wepl_runtime;

-- Only migrate writes the migration history.
REVOKE INSERT, UPDATE ON django_migrations FROM wepl_runtime;

-- Every table that already carries an append-only trigger (its function is
-- named <table>_append_only, by persistence.postgres.append_only or by hand).
DO $$
DECLARE tbl regclass;
BEGIN
    FOR tbl IN SELECT DISTINCT t.tgrelid::regclass FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid
              WHERE p.proname LIKE '%\_append\_only' AND NOT t.tgisinternal
    LOOP
        EXECUTE format('REVOKE UPDATE ON %s FROM wepl_runtime', tbl);
    END LOOP;
END $$;
"""

UNDO = """
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM wepl_runtime;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM wepl_runtime;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM wepl_runtime;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM wepl_runtime;
REVOKE USAGE ON SCHEMA public FROM wepl_runtime;
"""


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0002_existing_rows_follow_their_foreign_keys")]

    operations = [migrations.RunSQL(GRANTS, UNDO)]
