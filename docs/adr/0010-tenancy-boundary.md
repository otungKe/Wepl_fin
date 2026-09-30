# ADR-0010: Tenancy Boundary

- **Status:** Accepted (Harry, 2026-09-30). Recorded verbatim below.
- **Answers:** the open question in ADR-0009 ("who is the tenant?").
- **Implemented by:** ADR-0009's mechanism, plus a database rule of exactly
  one group per tenant (`communities_group.tenant_id` is unique). See
  "Implementation notes" at the end.

## Decision

Each independently governed group is a WEPL tenant.
An institution, provider, SACCO, bank, NGO, enterprise, or WEPL itself is not automatically the tenant merely because it serves or administers groups.
The group is the primary security and data-isolation boundary.

## Model

```text
Organization / Institution
        │
        │ serves / administers
        ▼
Tenant (Group)
        │
        ├── Members
        ├── Goals
        ├── Contributions
        ├── Wallets
        ├── Governance
        ├── Payments
        └── Financial records
```

An organization may have relationships with many tenants.
Example:

```text
I&M Bank
 ├── Group A → Tenant A
 ├── Group B → Tenant B
 └── Group C → Tenant C

SACCO X
 ├── Group D → Tenant D
 └── Group E → Tenant E

WEPL-direct
 ├── Group F → Tenant F
 └── Group G → Tenant G
```

## Core Principle

A tenant is:
An independently governed financial/data boundary whose records must be isolated from other tenants.
It is not necessarily the commercial customer, service provider, institution, or organization.

## Why

Group-level tenancy provides database-enforced isolation between groups.
This prevents the architecture from depending on application-level checks to keep groups apart.
The system should enforce:

```text
Tenant A cannot accidentally access Tenant B data.
```

at the database/security boundary.
Institution-level access is instead an explicit authorization relationship:

```text
Institution
      ↓
authorized relationship
      ↓
multiple tenants
```

## Institution Access

An institution may legitimately require access to multiple groups.
That access must be:

* explicitly authorized
* scoped
* auditable
* purpose-specific

Institutional access must NOT weaken tenant isolation.
The existence of an institution relationship must never imply unrestricted access to all tenant data.

## Tenant Isolation

Tenant isolation uses:

```text
Application tenant context
        +
Authorization
        +
PostgreSQL Row-Level Security
```

Application filtering alone is insufficient as the fundamental isolation mechanism.

## Context Implications

Every bounded context must explicitly declare its tenancy characteristics.
For each context determine whether its data is:

```text
GLOBAL
TENANT_SCOPED
USER_SCOPED
SYSTEM/CROSS_TENANT
```

Do not assume every model is tenant-scoped.
Do not assume every model is global.
The classification must follow the domain.

## Future Institutions

Do not design the system as though institutions can never become tenants.
If a future product capability establishes an independently governed institutional data boundary, that decision should be evaluated separately.
The current decision is:
Group is the default and primary tenant boundary for WEPL.
Changing this later would be an architectural decision requiring an ADR, not an incidental implementation change.

## Non-Negotiable Rule

Never implement:

```text
Institution = tenant
Group = application-only partition
```

as the default architecture.
Instead:

```text
Institution = organization/service/provider relationship
Group = tenant
```

unless a future, explicitly documented business requirement establishes another independently isolated tenant type.

---

## Implementation notes (not part of Harry's text)

- **One group per tenant is a database rule.** `communities_group.tenant_id`
  is unique. Onboarding provisions the group's tenant, then creates the
  group inside it. A second group in the same tenant is refused by
  PostgreSQL, so "group = application-only partition" cannot creep back in.
- **Keeping groups apart is RLS's job now.** The application checks that tie
  member, fund, mandate and line to one group stay as defence in depth.
  `tests/test_isolation.py` proves they still hold with row-level security
  deliberately widened by a declared cross-tenant operation.
- **Institutions are not built yet.** When they are, they get their own
  context, owning organizations and their relationships to tenants. Access
  goes through an explicit grant that is:
  - per tenant;
  - per purpose, for example "reconciliation" or "statement reporting";
  - time-bound and revocable;
  - audited on every use.

  It never goes through a standing cross-tenant scope. `cross_tenant()`
  stays reserved for WEPL's own system jobs.
