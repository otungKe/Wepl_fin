"""SQL for append-only tables, used by migrations in several contexts."""


def append_only(table: str) -> tuple[str, str]:
    """Return (forward, reverse) SQL making ``table`` reject UPDATE, DELETE and
    TRUNCATE. Corrections are new rows, never edits.

    Two independent locks (ADR-0027): the trigger refuses every role, and the
    application's role is not even granted UPDATE. It never had DELETE or
    TRUNCATE. The role comes from scripts/database_roles.sql."""
    fn = f"{table}_append_only"
    forward = f"""
    CREATE OR REPLACE FUNCTION {fn}() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP
            USING ERRCODE = 'restrict_violation';
    END $$;
    CREATE TRIGGER {fn}_row BEFORE UPDATE OR DELETE ON {table}
        FOR EACH ROW EXECUTE FUNCTION {fn}();
    CREATE TRIGGER {fn}_truncate BEFORE TRUNCATE ON {table}
        FOR EACH STATEMENT EXECUTE FUNCTION {fn}();
    REVOKE UPDATE ON {table} FROM wepl_runtime;
    """
    reverse = f"""
    DROP TRIGGER IF EXISTS {fn}_row ON {table};
    DROP TRIGGER IF EXISTS {fn}_truncate ON {table};
    DROP FUNCTION IF EXISTS {fn}();
    """
    return forward, reverse
