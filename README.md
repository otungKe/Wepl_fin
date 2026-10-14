# Wepl_fin

The WEPL money core. It keeps a register of who owns what in a group's pooled
money and the approvals (mandates) that authorise every payout. Each day it
reconciles that register against the account where the money is actually
held.

In the pilot, WEPL never holds money. Each group keeps its money in its own
Chama Account at the custodian bank. WEPL reads the statement, credits every pay-in to a member,
matches every payout to an approved mandate, and alerts every member when
money leaves without one.

## Run it

Requirements: Python 3.12 and PostgreSQL 16.

```sh
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements-dev.txt
cd backend
# Three roles (ADR-0027); the script also creates the database, owned by wepl_owner.
psql -U postgres -v db=wepl -f scripts/database_roles.sql
psql -U postgres -c "ALTER ROLE wepl_owner PASSWORD 'owner' CREATEDB" -c "ALTER ROLE wepl_app PASSWORD 'wepl'"
export DB_PASSWORD=wepl            # DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT override the defaults
export DB_OWNER_USER=wepl_owner DB_OWNER_PASSWORD=owner   # for the test runner only
DB_USER=wepl_owner DB_PASSWORD=owner python manage.py migrate   # only the owner migrates
python manage.py test              # the full suite, against real Postgres, as wepl_app
python manage.py demo_custody_pilot     # the scripted custody demo
```

### Database roles (ADR-0027)

| Role | What it is | What it may do |
|---|---|---|
| `wepl_owner` | Owns the schema; runs `migrate` | Everything on its own tables. Its login stays with WEPL operations, never on the application servers |
| `wepl_runtime` | Cannot log in; holds the application's privileges | `SELECT, INSERT` everywhere; `UPDATE` where a row's state changes; never `UPDATE` on an append-only table; never `DELETE`, `TRUNCATE`, `REFERENCES` or `TRIGGER` |
| `wepl_app` | The application's login, a member of `wepl_runtime` | What `wepl_runtime` may. Owns nothing |

None is a superuser or BYPASSRLS, so row-level security binds all three
(ADR-0009). The application refuses to start (`tenancy.E002`) if its role
owns a table or holds a privilege it should not. A database migrated before
ADR-0027 belongs to `wepl_app`: running `scripts/database_roles.sql` again
hands it to `wepl_owner`, and the next `migrate` grants the rest.

| Command | What it does |
|---|---|
| `python manage.py sync_accounts` | For each tenant in turn: fetch statements for its linked accounts, account for them, reconcile |
| `python manage.py deliver_outbox` | Deliver queued notifications (to the log until an SMS provider is chosen) |

`WEPL_PROPERTY_EXAMPLES=500 python manage.py test tests.test_properties` runs the
property tests harder than the default of 40 random histories.

## Where things are

```
backend/
  config/            Django settings (the framework sits at the edges)
  contexts/          one package per bounded context
    identity/  communities/  governance/  ledger/  custody/  notifications/  audit/  shared_kernel/
  simulators/custodian_bank a simulated Chama Account at the custodian bank, for tests and the demo only
  persistence/       generic PostgreSQL helpers for migrations
  tests/             cross-context suites: properties, isolation, architecture
docs/
  architecture/      overview, the engineering guidelines, and the audit against them
  adr/               architecture decision records
.claude/skills/      agent skills: architecture, ledger, custody, testing, security
```

Start with [docs/architecture/overview.md](docs/architecture/overview.md). The
standing rules are in
[docs/architecture/engineering-guidelines.md](docs/architecture/engineering-guidelines.md).
