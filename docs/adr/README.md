# Architecture decision records

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-modular-monolith-on-django-and-postgres.md) | Modular monolith on Django 5.2 LTS and PostgreSQL; no Redis or Celery | Django 5.2 LTS accepted; rest proposed |
| [0002](0002-bounded-contexts.md) | The contexts, their layers and their public surfaces | Proposed |
| [0003](0003-ledger-model.md) | Double-entry, append-only ledger enforced in the domain and in PostgreSQL | Proposed |
| [0004](0004-cross-context-references.md) | How contexts refer to each other's records | Proposed |
| [0005](0005-group-as-isolation-boundary.md) | The group is the data-isolation boundary until tenancy is decided | Superseded in part by 0009 |
| [0006](0006-custody-detective-control.md) | Pilot custody: groups hold money at I&M; WEPL reconciles and alerts | Proposed |
| [0007](0007-application-layer-uses-own-orm.md) | Shortcut: application code uses its own context's ORM models directly | Proposed, shortcut |
| [0008](0008-who-may-act-before-login.md) | Only an active official (since 0011: a `correct_records` holder) may correct the books; opening balances need two; simulator refused in production | Proposed |
| [0009](0009-tenancy-with-row-level-security.md) | Multi-tenancy: explicit tenant context, application checks, forced PostgreSQL row-level security | Proposed (implements Harry's decisions) |
| [0010](0010-tenancy-boundary.md) | Each independently governed group is a tenant; institutions get explicit, scoped, audited relationships | **Accepted** (Harry) |
| [0011](0011-membership-titles-and-capabilities.md) | Membership, an optional title (a label) and explicit capabilities are separate; a title grants nothing | Proposed (answers Harry's role review) |
| [0012](0012-membership-is-small.md) | Membership owns only group, status, code and title; Segment describes the group; LEFT is final; member codes are never reused, enforced in PostgreSQL | Proposed (answers Harry's membership review) |
| [0013](0013-founding-a-group.md) | A group founds its own tenant in one transaction; funds are opened separately; Segment removed; PostgreSQL allocates member codes on every insert | Proposed (follows Harry's application-layer review) |
| [0014](0014-leaver-balances.md) | Does a leaver's unpaid balance share interest and charges until settled? Today it is frozen by accident; pinned by a test | **Open**: waiting on Harry |

All are **Proposed** until Harry accepts them. Harry's
[foundational decisions](../architecture/foundational-decisions.md)
(2026-09-30) settled Django 5.2 LTS and database-enforced tenancy.
