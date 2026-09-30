# Architecture decision records

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-modular-monolith-on-django-and-postgres.md) | Modular monolith on Django 5.2 LTS and PostgreSQL; no Redis or Celery | Proposed |
| [0002](0002-bounded-contexts.md) | The contexts, their layers and their public surfaces | Proposed |
| [0003](0003-ledger-model.md) | Double-entry, append-only ledger enforced in the domain and in PostgreSQL | Proposed |
| [0004](0004-cross-context-references.md) | How contexts refer to each other's records | Proposed |
| [0005](0005-group-as-isolation-boundary.md) | The group is the data-isolation boundary until tenancy is decided | Proposed, open question |
| [0006](0006-custody-detective-control.md) | Pilot custody: groups hold money at I&M; WEPL reconciles and alerts | Proposed |
| [0007](0007-application-layer-uses-own-orm.md) | Shortcut: application code uses its own context's ORM models directly | Proposed, shortcut |

All are **Proposed** until Harry accepts them. A separate proposal
(`claude/project-thread-sdt0p6`, "ADR-0001: Stack") chose Django 6.0 with
HTMX; the difference is recorded as an open question in ADR-0001.
