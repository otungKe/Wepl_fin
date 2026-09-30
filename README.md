# Wepl_fin

The WEPL money core: a register of who owns what in a group's pooled money, the
approvals (mandates) that authorise every payout, and daily reconciliation
against the account where the money is actually held.

WEPL never holds money. In the pilot, each group keeps its money in its own
I&M Bank Chama Account; WEPL reads the statement, attributes every pay-in to a
member, matches every payout to an approved mandate, and alerts every member
when money leaves without one.

## Run it

Requirements: Python 3.12 and PostgreSQL 16.

```sh
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
createdb wepl                      # DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT override the defaults
python manage.py migrate
python manage.py test tests        # the full suite, against real Postgres
python manage.py demo_im_pilot     # the scripted I&M demo
```

Other commands:

| Command | What it does |
|---|---|
| `python manage.py sync_accounts` | Fetch statements for every connected account, process them and reconcile |
| `python manage.py deliver_outbox` | Deliver queued notifications (to the log until an SMS provider is chosen) |

`WEPL_PROPERTY_EXAMPLES=500 python manage.py test tests.test_properties` runs the
property tests harder than the default 40 random histories.

## Layout

| Module | Responsibility |
|---|---|
| `ledger` | Double-entry, append-only journal. Knows only ids and amounts. |
| `governance` | Groups, members, versioned constitutions, proposals, approvals, mandates |
| `connectivity` | Custodian accounts, statement ingestion, attribution, mandate matching, alerts, reconciliation |
| `parties` | People and phone numbers |
| `platform_core` | Audit log, transactional outbox, notifier port, SQL helpers |
| `simulator` | A simulated I&M Chama Account with fault injection, for tests and the demo only |

See [docs/architecture.md](docs/architecture.md) for the design, the invariants
and how each maps to the evidence I&M asked for.
