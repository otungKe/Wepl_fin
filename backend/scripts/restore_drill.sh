#!/usr/bin/env bash
# Restore drill (docs/operations/restore-drill.md).
#
# Backs up a database, restores the backup into a fresh scratch database,
# then proves the copy is the same and still works:
#   1. every table's rows are identical (count and checksum);
#   2. row-level security, its policies, the triggers and the database
#      functions that guard the money are all still there;
#   3. the application, connected to the copy, finds no unapplied
#      migration, passes the ledger integrity check and can read the
#      operator inbox.
# The scratch database and the backup file are removed at the end.
#
# Usage, from backend/:  scripts/restore_drill.sh SOURCE_DB
# Needs: PGHOST/PGPORT/PGUSER/PGPASSWORD for a role that can read every row
# and create databases (the database administrator), and the application's
# own DB_USER/DB_PASSWORD for step 3.
set -euo pipefail

SOURCE="${1:?usage: scripts/restore_drill.sh SOURCE_DB}"
SCRATCH="${SOURCE}_restore_drill"
DUMP="$(mktemp "${TMPDIR:-/tmp}/wepl-drill-XXXXXX.dump")"

cleanup() { dropdb --if-exists "$SCRATCH" >/dev/null 2>&1 || true; rm -f "$DUMP" "$DUMP.source" "$DUMP.copy" "$DUMP.diff"; }
trap cleanup EXIT

q() { psql -X -q -t -A -v ON_ERROR_STOP=1 -d "$1" -c "$2"; }

# What must be identical in the copy: every row of every table, and every
# guard the database enforces. Rows are hashed in a fixed order.
fingerprint() {
  local db="$1"
  for t in $(q "$db" "SELECT quote_ident(tablename) FROM pg_tables WHERE schemaname = 'public' ORDER BY 1"); do
    echo "table $t $(q "$db" "SELECT count(*) || ' ' || coalesce(md5(string_agg(x::text, E'\n' ORDER BY x::text)), '-') FROM $t x")"
  done
  q "$db" "SELECT 'rls ' || relname || ' ' || relrowsecurity || ' ' || relforcerowsecurity FROM pg_class
           WHERE relnamespace = 'public'::regnamespace AND relkind = 'r' ORDER BY relname"
  q "$db" "SELECT 'policy ' || tablename || ' ' || policyname || ' ' || md5(coalesce(qual, '') || coalesce(with_check, ''))
           FROM pg_policies WHERE schemaname = 'public' ORDER BY 1"
  q "$db" "SELECT 'trigger ' || tgrelid::regclass || ' ' || tgname || ' ' || tgenabled::text FROM pg_trigger
           WHERE NOT tgisinternal ORDER BY 1"
  q "$db" "SELECT 'function ' || proname || ' ' || md5(prosrc) FROM pg_proc
           WHERE pronamespace = 'public'::regnamespace ORDER BY 1"
}

echo "== Backing up $SOURCE"
started=$(date +%s)
pg_dump --format=custom --file="$DUMP" "$SOURCE"
echo "   $(du -h "$DUMP" | cut -f1) in $(( $(date +%s) - started ))s"

echo "== Restoring into $SCRATCH"
started=$(date +%s)
owner="$(q postgres "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = '$SOURCE'")"
dropdb --if-exists "$SCRATCH"
createdb --template=template0 --owner="$owner" "$SCRATCH"
pg_restore --exit-on-error --dbname="$SCRATCH" "$DUMP"
echo "   restored in $(( $(date +%s) - started ))s"

echo "== 1-2. Comparing every row and every database guard"
fingerprint "$SOURCE" > "$DUMP.source"   # files, not pipes, so a failing query stops the drill
fingerprint "$SCRATCH" > "$DUMP.copy"
if ! diff "$DUMP.source" "$DUMP.copy" > "$DUMP.diff"; then
  echo "FAILED: the restored copy differs from $SOURCE:"
  head -40 "$DUMP.diff"
  exit 1
fi
echo "   identical: $(cut -d' ' -f1 "$DUMP.copy" | sort | uniq -c | xargs)"

echo "== 3. The application on the copy"
DB_NAME="$SCRATCH" python manage.py migrate --check
DB_NAME="$SCRATCH" python manage.py check_ledger_integrity
# The inbox reads every group; the command needs a signed-in operator, so call the use case directly.
DB_NAME="$SCRATCH" python manage.py shell -c "from contexts.operations.public import operator_inbox; \
print(len(operator_inbox(actor='system:restore-drill')), 'open item(s) in the operator inbox')"

echo "== Restore drill passed for $SOURCE"
