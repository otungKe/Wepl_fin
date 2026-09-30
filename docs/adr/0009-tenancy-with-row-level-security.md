# ADR-0009: Tenancy with explicit context and forced row-level security

- **Status:** Proposed. It implements Harry's
  [foundational decisions](../architecture/foundational-decisions.md) 2–10
  (CONFIRMED, 2026-09-30). Who the tenant is: **each group**, decided by
  Harry in [ADR-0010](0010-tenancy-boundary.md).
- **Supersedes in part:** ADR-0005.

## Context

Harry decided that WEPL is multi-tenant and that isolation is layered.
Application filtering alone is not enough; PostgreSQL row-level security (RLS)
is the final boundary. The layers are:

1. explicit tenant context;
2. application-level authorization and scoping;
3. PostgreSQL row-level security;
4. physical database enforcement.

Before this, groups were isolated by application checks only (ADR-0005).

The original WEPL had RLS, but it isolated nothing, for three reasons
(reverse-engineering report, C3):
- policies failed *open* when no tenant was set;
- journals had no tenant column;
- every user resolved to one default tenant.

This design avoids all three.

## Decision

### Who owns tenancy

A `tenancy` context owns tenants, tenant context, declared cross-tenant
operations, and the database mechanism. It owns **no business rule**
(decision 10). Every context still classifies its own tables and keeps its
own checks.

### Tenant context (decisions 3 and 7)

- **`tenancy.public.tenant(tenant_id)` is the only way to act on
  tenant-scoped data.**
  - It opens a transaction or savepoint.
  - It sets a *transaction-local* database setting (`app.tenant_id`) that the
    policies read.
  - The setting cannot outlive the transaction. On exit it is cleared, and on
    error the rollback clears it.
  - A worker on a reused connection therefore cannot inherit the last task's
    tenant. `test_context_is_cleared_after_each_block_and_after_a_failure`
    proves this.
- **Switching scope inside a block is refused.** That covers:
  - another tenant inside a tenant;
  - a tenant inside a cross-tenant operation;
  - a cross-tenant operation inside a tenant.

  Re-entering the same tenant is a no-op. The rule is pure:
  `tenancy/domain/scope.py::entry_refusal`.
- **Tenant identity is never derived from a row.** Jobs list tenants through a
  declared operation, then act for each in turn:
  - `sync_accounts`;
  - the outbox worker, `deliver_pending`, which also calls the provider with
    no tenant and no transaction open.

### Cross-tenant operations (decisions 6 and 8)

- **`cross_tenant(reason, actor=...)`** is the only way outside a tenant.
  - A reason is required.
  - It writes a `tenancy.cross_tenant` audit event every time.
  - It sets `app.cross_tenant`, which the policies honour.
- **Current uses:**
  - `provision_tenant`;
  - `tenant_ids`, the list of tenants a job iterates.

### The database (decisions 2, 5 and 8)

**Every TENANT_SCOPED table has:**
- a `tenant_id` foreign key to `tenancy_tenant`, NOT NULL;
- a `BEFORE INSERT` trigger that stamps `tenant_id` from the context, so
  application code never passes it;
- `ENABLE` and `FORCE ROW LEVEL SECURITY`;
- one policy, `USING` and `WITH CHECK`:
  `tenant_id = wepl_current_tenant() OR wepl_cross_tenant()`.

**The policy fails closed.** With no context, nothing is visible and no insert
passes (the tenant is NULL, so NOT NULL rejects it). A row cannot be written
or moved into another tenant.

**The application role is not a superuser and has no BYPASSRLS.** The role is
`wepl_app`, in CI too. A Django system check (`tenancy.E001`) and a test
refuse anything else, because RLS does not bind such roles.

**The ledger's deferred balance trigger runs at commit,** possibly after the
context has ended. It reads the entry under the entry's *own* `tenant_id`, so
RLS can never hide lines from the balance check and make an unbalanced entry
pass.

**Keys that clients or workflows supply are unique per tenant, not globally:**
- a proposal's `request_key`;
- a journal `idempotency_key`;
- an outbox `dedupe_key`.

One tenant can therefore neither collide with another nor probe for another's
keys.

### Classification (decision 4)

Every model declares `tenant_scope`. The build checks that each model has one
and that each TENANT_SCOPED table really has forced RLS, a policy and a
NOT NULL tenant (`tests/test_tenancy.py`).

| Data | Scope | Why |
|---|---|---|
| Groups, funds, memberships | TENANT_SCOPED | a group and its people's roles belong to its tenant |
| Constitutions, proposals, approvals, mandates | TENANT_SCOPED | governance of one group |
| Ledger accounts, journal entries, journal lines | TENANT_SCOPED | the money; the original WEPL left journals unscoped |
| Custodian accounts, statement lines, resolutions, payer mappings, alerts, reconciliations | TENANT_SCOPED | the bank's view of one group's money |
| Outbox messages | TENANT_SCOPED | they carry members' phone numbers |
| Audit events | TENANT_SCOPED, **tenant-less rows allowed** | Unusual case: system events (provisioning, cross-tenant access) belong to no tenant and are visible only cross-tenant |
| People (`identity.Person`) | USER_SCOPED | Unusual case: one person may be in groups in several tenants. Tenants reach a person only through a membership. With no login yet, there is no user context to enforce, so this is an application rule for now |
| Tenants | SYSTEM | the platform's own list |
| Simulated bank | GLOBAL | a test double for I&M's system, not WEPL data; never installed in production (ADR-0008) |

### What the application layer still does (decision 5)

**Commands still check group membership, officials and mandates** (ADR-0005,
ADR-0008). They are defence in depth: `tests/test_isolation.py` widens RLS
on purpose with a declared cross-tenant operation, and shows the checks
still refuse to mix groups and write nothing.
`tests/test_tenancy.py` tests the database layer with two tenants, using raw
SQL on purpose.

**Across tenants, another tenant's ids are invisible, not "forbidden".** A
command given one fails the same way as for an unknown id, and writes nothing.

## Who the tenant is (answered by ADR-0010)

**Each independently governed group is its own tenant** (Harry, ADR-0010).
- `communities_group.tenant_id` is unique, so a tenant holds exactly one
  group, and PostgreSQL refuses a second.
- Onboarding provisions the tenant, then creates the group inside it.
- Institutions are *relationships* to tenants, never tenants by default.
  When they are built, their access will be an explicit grant that is
  per-tenant, per-purpose and audited, not `cross_tenant()`.

## Alternatives considered

- **A separate database role for system jobs, with BYPASSRLS.** Stronger than a
  session flag, because application code could not set it. But it needs a
  second connection and credential, and a job would run with a bypass instead
  of acting per tenant. Revisit when there is an operator console or when
  cross-tenant reporting appears. For now, cross-tenant use is rare, audited,
  and confined to one module.
- **Schema or database per tenant.** Stronger physical separation, but
  migrations, pooling and reporting multiply. RLS was chosen by Harry.
- **A global `tenant` filter in a custom manager.** This is exactly what
  decision 5 calls a convenience, not a boundary. Not added: RLS already
  filters, and a manager would hide the explicit context.

## Consequences

**Everything touching tenant data needs a context.** That covers commands,
jobs, tests and the demo. Tests use `Scenario.acting()` or
`act_for_new_tenant`.

**A Postgres quirk to know.** `SET CONSTRAINTS` inside a released savepoint
survives the rollback of an outer savepoint. Fire deferred checks outside a
tenant block, and set them back to `DEFERRED` afterwards
(`tests/test_properties.py`).

**Revisit when any of these happens:**
- login lands, and the tenant comes from the session's membership;
- an operator console needs cross-tenant views, and the separate-role
  alternative is reconsidered;
- the first reporting job spans tenants.
