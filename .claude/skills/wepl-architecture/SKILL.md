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

The contexts are identity, communities, governance, ledger, custody,
notifications, audit and shared_kernel. ADR-0002 says what each owns and does
not own, and each context's `__init__.py` repeats it.

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

## Isolation: what is real and what is not (ADR-0005)

- **Real:**
  - Every command checks that the records it touches (member, fund, mandate,
    statement line) belong to the same group.
  - Mismatches raise, and `tests/test_isolation.py` proves it.
  - Audit rows carry `group_id`.
- **Not real yet:**
  - There is no tenant model.
  - There is no PostgreSQL row-level security.
  - Queries are scoped by application code, not by the database.
- **Do not describe group isolation to I&M or anyone outside the repo as a
  database-enforced security boundary.** The tenancy model (group, or an
  institution serving many groups) is an open question for Harry. When it is
  decided, each new tenant-scoped table needs its policy from day one.
- The original WEPL learned this the hard way: its tenancy mechanism was
  "done" while the user → tenant resolver returned one default tenant for
  everyone.

## ADR status

All of ADR-0001 to ADR-0007 are **Proposed** until Harry accepts them.
ADR-0007 is a recorded shortcut: application code uses its own context's ORM
models directly. "Proposed" does not mean absent; check the code.

## Commit conventions

Develop on the thread's branch. Commits end with the Co-Authored-By and
Claude-Session trailers the session gives you. Model names never go in commits
or PRs.
