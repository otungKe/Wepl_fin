# Wepl_fin

The WEPL money core. It keeps a register of who owns what in a group's pooled
money and the approvals (mandates) that authorise every payout. Each day it
reconciles that register against the account where the money is actually
held.

In the pilot, WEPL never holds money. Each group keeps its money in its own I&M
Bank Chama Account. WEPL reads the statement, credits every pay-in to a member,
matches every payout to an approved mandate, and alerts every member when
money leaves without one.

## Run it

Requirements: Python 3.12 and PostgreSQL 16.

```sh
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements-dev.txt
cd backend
# The app connects as wepl_app: not a superuser, so row-level security binds it (ADR-0009).
psql -U postgres -c "CREATE ROLE wepl_app LOGIN PASSWORD 'wepl' CREATEDB NOSUPERUSER NOBYPASSRLS"
createdb -U postgres -O wepl_app wepl   # DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT override the defaults
python manage.py migrate
python manage.py test              # the full suite, against real Postgres
python manage.py demo_im_pilot     # the scripted I&M demo
```

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
  simulators/im_bank a simulated I&M Chama Account, for tests and the demo only
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
