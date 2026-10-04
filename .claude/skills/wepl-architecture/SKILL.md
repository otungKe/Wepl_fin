---
name: wepl-architecture
description: Where code goes in Wepl_fin — the bounded contexts, their layers
  (domain / application / infrastructure / public surface), what the architecture
  test enforces, transactions and outbox rules, how far group isolation really
  reaches, and the ADRs. Use when adding a module, model, use case, integration
  or migration, or when unsure which context owns something.
---

# Wepl_fin architecture

The standing rules are Harry's 60 guidelines in
`docs/architecture/engineering-guidelines.md`. Read
`docs/architecture/overview.md` first. This skill is the practical layer
beneath them. Adapted from the original WEPL repo's `wepl-architecture` and
`wepl-tenancy` skills (PR #205).

## Before writing code

Answer these: what business concept is it, which context owns it, what
invariant does it protect, and what contract does it expose? If you cannot,
stop and ask. Never invent a requirement: mark it UNKNOWN or ASSUMPTION in an
ADR (guidelines 56–57).

## Where new code goes

| It is… | It belongs in… |
|---|---|
| a business rule, value object or state machine | `contexts/<ctx>/domain/` (pure Python, no Django) |
| an accounting decision (event → journal) | the owning context's domain, returning a `JournalDraft` |
| a use case (command) or read (query) | `contexts/<ctx>/application/` |
| a model, migration, connector, notifier or command | `contexts/<ctx>/infrastructure/` |
| something another context may call | `contexts/<ctx>/public.py` (functions) or `contract.py` (pure types) |
| a stand-in for an external system | `backend/simulators/` (never imported by a context) |
| generic PostgreSQL SQL for migrations | `backend/persistence/` |
| a structural decision | a **new** ADR in `docs/adr/`, indexed in its README |

The contexts are tenancy, identity, communities, governance, ledger, custody,
notifications, audit, operations (ADR-0020) and shared_kernel. ADR-0002 says what each owns and does
not own, and each context's `__init__.py` repeats it.

**Keep membership small (ADR-0012).** A membership holds only its group,
status (ACTIVE → LEFT, final), member code and optional title. Before adding
a field to it, ask: is this a fact about the person's membership in this
group, or a fact another context owns? Payments, balances, capabilities,
notifications, KYC and login are owned elsewhere. Member codes are
allocated from `Group.last_member_sequence`, never from a count.

## What the build enforces (`backend/tests/test_architecture.py`)

- **Boundaries.** A context imports another only via `contexts.<x>.public` or
  `contexts.<x>.contract`.
- **Pure code.** `domain/` and `contract.py` import no Django, database,
  simulator or config, and only other contexts' `contract` modules.
- **Context shape.** Every context has an ownership docstring ("Owns:" and
  "Does not own:") and a `public.py`.
- **Banned modules and patterns:**
  - no `utils.py`, `helpers.py`, `common.py`, `misc.py` or `services.py`;
  - no module over 250 lines;
  - no signals;
  - no mutable money counters.
- **ADRs.** Every ADR is indexed.

A red architecture test means the design moved. Fix the code, or write an ADR
that changes the rule. Never loosen the test quietly.

## Cross-context references (ADR-0004)

- **No model imports across contexts, ever.**
- **String foreign keys only where listed.** A foreign key to another
  context's table is declared by string (`"communities.Membership"`,
  `PROTECT`), and only for the relationships listed in ADR-0004. Adding one
  means adding a row there.
- **The ledger holds plain ids.** It stays the foundation and depends on
  nobody.
- **Linked rows share a tenant (ADR-0017).** Foreign key checks ignore RLS,
  so every key between tenant-scoped tables also carries the tenant: give the
  parent `tenant_keyed(...)` and the link `same_tenant(...)` from
  `persistence/tenancy.py`. A plain-id link gets a check trigger, installed
  by the context that already depends on the other one. The guard in
  `tests/test_linked_rows.py` fails the build when a link misses this.

## Transactions and side effects

- **Commands own their transactions.** Each command owns its
  `transaction.atomic` and states why in a comment. Custody ingests each
  statement line in its own transaction, with the external account row
  locked.
- **Notifications go in the change's transaction.** A notification is an
  outbox row written in the same transaction as the change that caused it
  (`notifications.public.notify`). Give it a `dedupe_key` so a retried
  workflow never messages twice. Payloads are JSON primitives; never an ORM
  object.
- **No network call inside a transaction.**
  - Outbox delivery claims a row under a 5-minute lease, calls the provider
    with no transaction open, then records the outcome
    (`notifications/application/delivery.py`).
  - Custody fetches from the connector before `ingest` opens any transaction.
  - Keep it that way.
  - **Watch out:** `ATOMIC_REQUESTS=True` in settings, so once HTTP views
    exist, a provider call from a view would be inside a transaction.
- **State changes are conditional.** They use `UPDATE … WHERE status =
  <expected>` (`governance/application/mandates.py::execute_mandate`). A
  result of 0 rows means another worker won; handle it, never retry blindly.
- **Traceability.** Wrap entry points in `audit.public.operation(name,
  actor=...)`. Audit records, journal entries, outbox rows and reconciliation
  runs carry its id.

## Providers (guidelines 21–22)

- **Selected by settings.** Custodian integrations implement
  `custody.contract.Connector`; the implementation is chosen by name from
  `settings.WEPL_CONNECTORS`. Notifiers implement
  `notifications.application.ports.Notifier` and are chosen by
  `settings.WEPL_NOTIFIER`.
- **No vendor names in the domain.** Vendor fields stay in `metadata`: a
  statement line's id is `external_id`, never `mpesa_receipt` or
  `bank_txn_id`.
- **The simulator is a dev-only app.** It is installed only when
  `WEPL_ENABLE_SIMULATOR=1`, the default for dev and CI. Production must set
  it to 0.

## Tenancy and isolation (ADR-0009, foundational decisions)

Harry's [foundational decisions](../../../docs/architecture/foundational-decisions.md)
make tenancy a layered security boundary:

```text
explicit tenant context → application checks → PostgreSQL RLS (forced) → database
```

- **Act inside a tenant.** Any code touching tenant data runs inside
  `tenancy.public.tenant(tenant_id)`. Without it, the database shows nothing
  and refuses every insert. That is deliberate: the policy fails closed.
- **Jobs iterate tenants.** Use `tenant_ids(reason=..., actor=...)`, then act
  for each tenant in turn. Never derive the tenant from a row.
- **Outside a tenant, declare it.** Use `cross_tenant(reason, actor=...)`. It
  is audited every time. Never add a convenient cross-tenant query.
- **Never switch tenants inside a block.** It raises. Finish one tenant's work
  first.
- **Every new model declares `tenant_scope`:** GLOBAL, TENANT_SCOPED,
  USER_SCOPED or SYSTEM. Choose it from the domain, and document unusual
  cases in ADR-0009.
- **A TENANT_SCOPED model** gets `tenant = tenant_column()` (from
  `persistence.tenancy`), plus a migration that runs
  `RunSQL(*tenant_scoped(table))`. `tests/test_tenancy.py` fails the build if
  either is missing.
- **Keys a client or workflow supplies are unique per tenant**
  (`UniqueConstraint(fields=["tenant", ...])`), never globally.
- **A trigger that reads other rows** runs under row-level security. If it
  can fire after the context ends, as deferred triggers do, set the tenant
  from `NEW.tenant_id` inside it, as the ledger's balance check does.
- **Connect as `wepl_app`.** It is not a superuser and has no BYPASSRLS, or
  RLS silently does nothing. The `tenancy.E001` check and a test enforce it.
- **Group checks stay.** Commands still verify that member, fund, mandate and
  line belong to one group. They are defence in depth, and they are tested
  with RLS deliberately widened (`tests/test_isolation.py`).
- **A group is a tenant (ADR-0010, accepted).**
  - Exactly one group per tenant: the database refuses a second.
  - `create_group` founds the group *and* its tenant in one transaction,
    outside any tenant (ADR-0013). Never provision a tenant and then create
    a group inside it.
  - Institutions, providers, SACCOs and WEPL-direct *relate to* tenants;
    they are never tenants by default.
  - Institution access, when built, is an explicit grant: per tenant, per
    purpose, audited. It is never `cross_tenant()`.
  - **Never build "institution = tenant, group = application-only
    partition".** Changing the boundary needs a new ADR.

## ADR status

ADR-0001 (Django 5.2 LTS) is accepted; the rest are **Proposed** until Harry accepts them. Never move to Django 6.x without a named need and an ADR.
ADR-0007 is a recorded shortcut: application code uses its own context's ORM
models directly. "Proposed" does not mean absent; check the code.

## Commit conventions

Develop on the thread's branch. Commits end with the Co-Authored-By and
Claude-Session trailers the session gives you. Model names never go in commits
or PRs.
