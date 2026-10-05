# Architecture decision records

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-modular-monolith-on-django-and-postgres.md) | Modular monolith on Django 5.2 LTS and PostgreSQL; no Redis or Celery | Django 5.2 LTS accepted; rest proposed |
| [0002](0002-bounded-contexts.md) | The contexts, their layers and their public surfaces | Proposed |
| [0003](0003-ledger-model.md) | Double-entry, append-only ledger enforced in the domain and in PostgreSQL; a reversal is reversible, each entry at most once | **Accepted** (Harry, 2026-10-03) |
| [0004](0004-cross-context-references.md) | How contexts refer to each other's records | Proposed |
| [0005](0005-group-as-isolation-boundary.md) | The group is the data-isolation boundary until tenancy is decided | Superseded in part by 0009 |
| [0006](0006-custody-detective-control.md) | Pilot custody: groups hold money at the custodian bank; WEPL reconciles and alerts | Proposed |
| [0007](0007-application-layer-uses-own-orm.md) | Shortcut: application code uses its own context's ORM models directly | Proposed, shortcut |
| [0008](0008-who-may-act-before-login.md) | Only an active official (since 0011: a `correct_records` holder) may correct the books; opening balances need two; simulator refused in production | Proposed |
| [0009](0009-tenancy-with-row-level-security.md) | Multi-tenancy: explicit tenant context, application checks, forced PostgreSQL row-level security | Proposed (implements Harry's decisions) |
| [0010](0010-tenancy-boundary.md) | Each independently governed group is a tenant; institutions get explicit, scoped, audited relationships | **Accepted** (Harry) |
| [0011](0011-membership-titles-and-capabilities.md) | Membership, an optional title (a label) and explicit capabilities are separate; a title grants nothing | Proposed (answers Harry's role review) |
| [0012](0012-membership-is-small.md) | Membership owns only group, status, code and title; Segment describes the group; LEFT is final; member codes are never reused, enforced in PostgreSQL | Proposed (answers Harry's membership review) |
| [0013](0013-founding-a-group.md) | A group founds its own tenant in one transaction; funds are opened separately; Segment removed; PostgreSQL allocates member codes on every insert | Proposed (follows Harry's application-layer review) |
| [0014](0014-leaver-balances.md) | Does a leaver's unpaid balance share interest and charges until settled? Each group chooses in its constitution; judged on the event's date | Decided: every leaver rule is the group's choice; built |
| [0015](0015-fund-lifecycle.md) | A fund is opened, renamed while open, closed only when empty in the ledger, governance and custody, never reopened or deleted | Accepted |
| [0016](0016-derived-balances-at-scale.md) | Balances stay derived from full history; measured, with indexes RLS can use; checkpoints only past 100,000 lines in a fund | Proposed (follows Harry's measurement request) |
| [0017](0017-linked-rows-keep-their-tenant.md) | A row and every row it refers to share a tenant: composite foreign keys, plus checks for plain ids installed by the dependent context | **Accepted** (Harry); implemented |
| [0018](0018-pooled-collection-account.md) | One WEPL collection account, each fund a sub-ledger, routed by payment reference | Withdrawn (Harry, 2026-10-04): kept as a fallback; code in commit `79cb91f` |
| [0019](0019-collections-service-on-each-group-account.md) | The bank's collections service on each group's own account: the reference check and notifications go straight to that group; the reference is the member's mobile number | **Accepted** (Harry, 2026-10-04); request format and signing wait on the bank |
| [0020](0020-operations-inbox-and-nightly-run.md) | An operations context: the nightly run drives each context's job in order, an operator inbox reads every group in turn, and a counts-only daily email digest | **Accepted** (Harry, 2026-10-05); built |
| [0021](0021-operator-login.md) | How WEPL staff sign in: provisioned accounts, password plus authenticator, staged server-side sessions, capabilities that fail closed | **Accepted** (Harry, 2026-10-05), roles support, onboarding, admin; built |
| [0022](0022-contributions-and-arrears.md) | Contributions and arrears: each fund's rule is the group's own constitution setting (schedule, amount, payment order, fines, leavers' arrears); arrears derived | **Accepted** (Harry, 2026-10-05); built, with fines funds and waivers |
| [0023](0023-one-account-holds-the-groups-funds.md) | One bank account holds all of a group's funds: fund code in the reference, else the default fund; interest and charges split as the group chooses; reconcile the account against all its funds | **Accepted** (Harry, 2026-10-05); built |

All are **Proposed** until Harry accepts them. Harry's
[foundational decisions](../architecture/foundational-decisions.md)
(2026-09-30) settled Django 5.2 LTS and database-enforced tenancy.
