# Restore drill

`backend/scripts/restore_drill.sh SOURCE_DB` proves that a backup of WEPL
can be restored and is fit to use. CI runs it on every change, against the
database the custody demo has just filled.

## What it proves

1. **Every row survives.** Each table's row count and a checksum over all of
   its rows match the source exactly.
2. **Every database guard survives.** These all match the source:
   - row-level security, enabled and forced, on every table;
   - every policy, by name and by text;
   - every trigger and its state;
   - every function, by its source.
3. **The application works on the copy.**
   - It finds no unapplied migration.
   - It passes the ledger integrity check (trial balance zero and the fund
     position invariant, for every fund).
   - It can read the operator inbox.

It also prints the backup size and how long the backup and the restore took.

## Running it on a real database

- Run it from `backend/`.
- It needs two sets of credentials:
  - the database administrator's, in `PGHOST`, `PGUSER` and `PGPASSWORD`;
  - the application's own, in `DB_USER` and `DB_PASSWORD`.
- It restores into a scratch database, `<SOURCE>_restore_drill`, and drops
  it at the end. The source is only read.
- ASSUMPTION: the hosting provider's own backups are restored the same way
  (`pg_restore` of a custom-format dump). If the provider uses snapshots
  instead, run steps 1–3 against the restored snapshot.

Suggested cadence: monthly, and after every change to the backup setup.
Keep the output as evidence for the bank.

## What its first run found (2026-10-04)

- **The finding.** The first drill would not restore the development
  database. One membership row named a group in another tenant, yet the key
  that forbids exactly that (ADR-0017) was marked valid.
- **The cause** (CONFIRMED with a minimal reproduction on PostgreSQL 16).
  When a foreign key is added, PostgreSQL checks the rows already in the
  table with an ordinary query. Under forced row-level security, with no
  tenant context, that query sees no rows. The key is then marked valid
  without having checked anything.
  - The row was a test probe written on 2026-09-30, before the key existed.
  - Production has no data yet, so nothing real was affected.
- **The fix:**
  - every key is now added in a cross-tenant step (`persistence/tenancy.py`);
  - tenancy migration 0002 re-adds every existing key the same way, so a
    database whose rows break a key now refuses to migrate;
  - regression tests in `tests/test_tenancy.py` fail without the fix.
