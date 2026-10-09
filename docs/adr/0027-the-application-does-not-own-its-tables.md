# ADR-0027: The application does not own its tables

- **Status:** **Accepted** (Harry, 2026-10-09), steps 1–6 built. Drafted by
  Claude after the ledger hardening review's finding H1
  (`docs/architecture/review-ledger-hardening.md`). Harry's terms:
  - WEPL operations holds the owner's credentials, apart from the
    application servers;
  - the role split is one focused change;
  - the seal (step 7) is a separate follow-up, unless its severity requires
    it before the role split is deployed (see "The seal after the split");
  - accepted subject to verifying the actual privileges and the seal, which
    "Verified" below records.
- **Touches:** ADR-0003 (append-only ledger), ADR-0009 (row-level security),
  ADR-0017 (linked rows keep their tenant), ADR-0020 (nightly run and restore
  drill), and every context's migrations.

## Context

Foundational decision: PostgreSQL is the final enforcement boundary, not
the application. Today that holds against application bugs, but not against
someone who can run SQL as the application.

- **One role does both jobs.** `wepl_app` runs the migrations, so it owns
  every table, and the application connects as the same role. That is the
  setup in CI and in the README.
- **An owner can turn the rules off.** It can disable its tables'
  triggers, drop or change their policies, turn off `FORCE ROW LEVEL
  SECURITY` and drop constraints.
- **The review proved it.** CONFIRMED on 2026-10-06, as `wepl_app`:
  `ALTER TABLE ledger_journalline DISABLE TRIGGER
  ledger_journalline_append_only_row`, then an `UPDATE` of a posted line's
  amount, succeeded. The ledger's balance triggers can be disabled the same
  way. The ledger's own bypass tests (`test_integrity.py`) depend on it.
- **The seal can be forged.** The setting that seals posted entries
  (`wepl.ledger_open_entries`, ledger 0005) can be set by any session. A
  balanced pair of lines was added to an entry committed earlier.
- **Who this protects against.** An SQL injection, a compromised server or
  a careless shell session holds the application's credentials. With them,
  it can rewrite financial history and read every group's data. The bank's
  due diligence will ask exactly this.

ADR-0009 already makes sure the role is not a superuser and has no BYPASSRLS
(`tenancy.E001`). This ADR closes the remaining gap: ownership.

## Decision

1. **Two roles.**
   - **`wepl_owner`** owns the schema and every table, function, trigger and
     policy. It runs `migrate` and nothing else. It cannot log in from the
     application servers. It is neither a superuser nor BYPASSRLS.
   - **`wepl_runtime`** is a `NOLOGIN` group role holding the application's
     privileges. The login role the application uses (`wepl_app`) is a member
     of it and owns nothing.
2. **Privileges follow each table's history rule.** They are granted by
   migrations, next to the rule they back:

   | Table kind | `wepl_runtime` gets | Examples |
   |---|---|---|
   | Append-only | `SELECT, INSERT` | ledger accounts, entries, lines and integrity checks; audit events; constitutions, approvals, votes and capability changes; statement lines, line resolutions and reconciliation runs; operator events |
   | Has a state that changes | `SELECT, INSERT, UPDATE` | mandates, proposals, transfers, funds (rename, close), the outbox |
   | Any table | never `DELETE`, `TRUNCATE`, `REFERENCES`, `TRIGGER` or ownership | |

   - No application code deletes a row today; CONFIRMED by searching the
     contexts for `.delete()`.
   - Sequences get `USAGE, SELECT`.
   - The append-only triggers stay. Privilege and trigger become two
     independent locks, and the trigger still gives the clear error message.
3. **Every table is classified, or the build fails.** `persistence/postgres.append_only()`
   also emits the `REVOKE UPDATE` for its table. Default privileges
   (`ALTER DEFAULT PRIVILEGES`, run by `wepl_owner`) give a new table
   `SELECT, INSERT, UPDATE`, so a forgotten append-only table fails safe on
   its trigger, not open. An append-only table is any table with a trigger
   whose function is named `<table>_append_only` (the helper's, or a
   hand-written one such as `communities_fundcode`'s). The boot check below
   finds any of them with an `UPDATE` grant, and the suite runs it.
4. **A boot check, `tenancy.E002`.** It refuses to start if the connected
   role owns any table, sequence or function in the schema (directly or by
   membership), can `UPDATE` an append-only table, holds `DELETE`,
   `TRUNCATE`, `REFERENCES` or `TRIGGER` on any table, or can `CREATE` in the
   schema. This sits beside `E001` (superuser or BYPASSRLS). The schema owner
   is recognised by name (`WEPL_SCHEMA_OWNER`, default `wepl_owner`) and gets
   only a warning, `tenancy.W001`, so `migrate` can run as it.
5. **A test as the runtime role.** It shows each of these is refused:
   - `ALTER TABLE … DISABLE TRIGGER`;
   - `DROP POLICY`;
   - `ALTER TABLE … NO FORCE ROW LEVEL SECURITY`;
   - `UPDATE`, `DELETE` and `TRUNCATE` on the ledger's tables;
   - `CREATE TRIGGER`.

   The suite runs as `wepl_app` in CI. The test runner
   (`tests/database_roles.py`) creates and migrates the test database as
   `wepl_owner`, whose login is configured for tests only (`DB_OWNER_USER`;
   with `DEBUG` off the settings refuse it). Another test proves, as the
   owner, that every append-only trigger still refuses `UPDATE`, `DELETE`
   and `TRUNCATE`: the second lock.
6. **Bypass tests act as the owner.** The tests that turn a rule off (to
   prove the nightly check catches what the balance triggers would have
   refused, or that a second currency stays apart) and the tests of
   migration SQL subclass `AsSchemaOwner`: the whole test case connects as
   `wepl_owner`. That is honest: only the schema owner, a superuser or a
   restore can do that. (A second connection cannot do it inside a test's
   transaction: `ALTER TABLE` waits for the locks that transaction holds.)
7. **The seal stops relying on a setting.** Once the runtime role can no
   longer drop the trigger, the remaining forgery is the session setting.
   The line trigger then decides "is this entry still open?" from the entry
   row's inserting transaction: still in progress means it is this
   transaction's, since another's uncommitted row is invisible. It no
   longer reads `wepl.ledger_open_entries`. This step is separate and comes
   after steps 1–6.
8. **Operations.**
   - **CI** creates both roles.
   - **The restore drill** keeps running as the database administrator and
     also checks the grants are restored: `pg_dump` keeps them; the drill
     compares `information_schema.role_table_grants`.
   - **The README** documents the two roles and what each may do.
   - **Deployment** runs `migrate` with the owner's credentials, held apart
     from the application's.

## Verified (2026-10-09)

- **Before** (CONFIRMED, local database at main `b3d2dad`): `wepl_app` owned
  all 40 tables and 49 functions in the schema.
- **After** (CONFIRMED, `tests/test_database_roles.py`): `wepl_app` owns
  nothing. It is refused, for want of privilege, `DISABLE TRIGGER`,
  `DROP TRIGGER`, `DROP POLICY`, `NO FORCE ROW LEVEL SECURITY`,
  `DROP CONSTRAINT`, `CREATE TRIGGER`, replacing a policy function,
  `CREATE TABLE` and `SET ROLE wepl_owner`; `UPDATE`, `DELETE` and
  `TRUNCATE` on all 15 append-only tables; and `DELETE` on every table.
- **Two code changes** the missing privileges required, because
  PostgreSQL needs `UPDATE` to lock a row:
  - adopting a constitution locked its latest version `FOR UPDATE`; it now
    takes a transaction-scoped advisory lock per group
    (`governance/infrastructure/locks.py`), with a race test;
  - deciding a proposal, transfer or waiver locked its constitution too,
    through `select_related`; it now locks only its own row (`of=("self",)`).
- **The restore drill** compares each table's owner and grants, and the
  default privileges, and runs `tenancy.E002` on the copy.

### The seal after the split

CONFIRMED (2026-10-09, as `wepl_app` after the split, rolled back): setting
`wepl.ledger_open_entries` to an old entry's id and inserting a balanced
pair of lines on two members' accounts was accepted, and the balance checks
passed. So with the application's credentials one can still move money
between members inside an entry posted earlier.

Severity: Medium, not a blocker for the split. The split already took away
editing, deleting and turning rules off. What remains needs only `INSERT`,
which the application must keep; the same person could post a new entry
just as well. What the forged seal adds is concealment: the change sits
inside an old, approved entry instead of appearing as a new one. Nothing
runs in production yet. Step 7 should land before the pilot handles real
money, as the next ledger change.

## Alternatives considered

- **Keep one role and rely on review.** Rejected. It leaves the history and
  isolation guarantees depending on nobody ever running SQL as the
  application, which is the threat the database layer exists for.
- **Revoke privileges from the owner instead.** Not possible: an owner can
  always grant its privileges back to itself, and can change its tables'
  triggers and policies.
- **`SECURITY DEFINER` functions for every write** (the application gets
  `EXECUTE` only). Stronger, but it moves the write path out of Django and
  the contexts' own code. That is a redesign; this ADR keeps the current
  write path.
- **Event triggers that refuse `ALTER TABLE`.** Creating one needs a
  superuser, and it would not stop an owner changing policies.

## Consequences

- A compromised application can no longer edit or delete history, turn off a
  rule, or widen its own view of other tenants. It can still insert, and
  read within RLS. What it inserts passes every trigger and constraint.
- Migrations need the owner's credentials. Running `migrate` as `wepl_app`
  fails, by design.
- Every new table needs its history rule declared (decision 3). This matches
  how each table already declares its tenant scope.
- The test setup gains one database alias, and the bypass tests use it.
- No data changes. `scripts/database_roles.sql` (run by the database
  administrator) creates the roles and hands an existing database to the
  owner (`REASSIGN OWNED BY wepl_app TO wepl_owner`); tenancy migration 0003
  then grants the runtime role its share. Both are reversible by the
  database administrator.
- `app.cross_tenant` and `app.tenant_id` are still session settings the
  application sets. That is by design (ADR-0009): RLS binds the application
  to its declared context, and a forged context is visible in the audit only
  if declared. ADR-0009's alternative (a separate BYPASSRLS role for system
  jobs) stays a later option, as that ADR says.

## Answered

1. **Credentials.** WEPL operations holds the owner's credentials, apart
   from the application servers (Harry, 2026-10-09). Where production
   PostgreSQL runs is still open; both options support separate roles.
2. **Order of work.** Steps 1–6 as one change, step 7 as a follow-up
   (Harry, 2026-10-09).
