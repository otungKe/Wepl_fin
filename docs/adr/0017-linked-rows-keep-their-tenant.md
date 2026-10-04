# ADR-0017: A row and every row it refers to belong to the same tenant

- **Status:** Accepted and implemented (Harry, 2026-10-01: "lets build
  ADR-0017"). Harry asked for this record: "relationships crossing bounded
  contexts must preserve tenant and group ownership consistently, without
  creating inappropriate direct dependencies between contexts." It follows
  from the membership review (C1).
- **Implemented in:** ledger 0008, communities 0013, governance 0006,
  custody 0005 (helpers in `persistence/tenancy.py`). The guard and the
  probes are in `tests/test_linked_rows.py`. Every write in the probe table
  below is now refused, inside a tenant and inside a cross-tenant operation.

## Context

Row-level security (ADR-0009) decides which rows a query **sees** and which
rows it may **write**. It does not decide what a written row may **point at**.

**PostgreSQL checks foreign keys without row-level security.** A row
stamped with tenant A can name a parent that belongs to tenant B, and the
foreign key accepts it.

This was CONFIRMED by probe on 2026-10-01, as the application role, using
raw ORM writes. Every one of these was **accepted**:

| Write | Mode |
|---|---|
| A payer mapping in tenant A naming B's group and B's member | inside tenant A |
| A capability grant in tenant A to B's member | inside tenant A |
| Both of the above | inside a declared cross-tenant operation |
| A ledger entry in tenant A naming B's group and B's fund | inside tenant A, through `post_journal` |

(Before ADR-0017 was implemented.) Nothing **reads** across the boundary afterwards. Tenant A's row is still
invisible to B, and B's rows are still invisible to A. But the row is
wrong: it claims a relationship with another group's member or fund.

Today only the application prevents this:
- `member_of`, `fund_view` and similar look the parent up under RLS, so a
  foreign id reads as "unknown";
- every current command does that (INFERRED from code review).

Only five relationships are checked in the database:

| Relationship | Where |
|---|---|
| membership → group | communities 0009 |
| fund → group | communities 0010 |
| journal line → entry, account | ledger 0005 |
| reversal → reversed entry | ledger 0005 |

### Inventory

**Declared foreign keys between tenant-scoped tables (25 not checked):**
- **communities:** fund.group *(checked)*, membership.group *(checked)*.
- **custody:**
  - externalaccount.group, .fund;
  - statementline.external_account;
  - lineresolution.line, .membership, .mandate;
  - payermapping.group, .membership;
  - alert.group, .line;
  - reconciliationrun.external_account.
- **governance:**
  - constitution.group;
  - proposal.group, .fund, .constitution, .proposed_by, .charged_member;
  - approval.proposal, .membership;
  - mandate.group, .fund, .proposal, .charged_member;
  - capabilitychange.group, .membership.
- **ledger:** line.entry, line.account, entry.reverses *(all checked)*.
- **Exempt:** membership.person → identity.Person. Person is USER_SCOPED: one
  person may belong to groups in many tenants by design (ADR-0012).

**Plain-id references** (ADR-0004 keeps these contexts independent):
- **ledger:** account and entry group_id, fund_id; account member_id,
  external_account_id;
- **custody:** lineresolution.journal_entry_id;
- **governance:** mandate.executed_by_line_id;
- **audit:** event.group_id. This is descriptive and written by the tenant's
  own operations; listed, with no constraint proposed.

## Decision

1. **The rule.** A tenant-scoped row and every tenant-scoped row it refers
   to have the same `tenant_id`.
   - PostgreSQL enforces it.
   - It holds inside a tenant, inside a declared cross-tenant operation, and
     for a superuser.
   - Application checks stay, for clear errors, but they are not the
     guarantee.
2. **Group follows from tenant.**
   - A tenant has exactly one group (ADR-0010; unique constraint
     `community_one_group_per_tenant`).
   - So "same tenant" also means "same group", and a fund or membership in
     the same tenant is in the same group.
   - If ADR-0010 ever allows several groups per tenant, this ADR must be
     revisited, and group-level composite keys added.
3. **Declared foreign keys become composite.**
   - `(parent_id, tenant_id) REFERENCES parent (id, tenant_id)`, deferrable
     like the existing keys.
   - Each parent gains `UNIQUE (id, tenant_id)`.
   - The referencing context's migration adds it, beside the key it already
     declares (ADR-0004). This adds no new dependency between contexts: the
     dependency is the one already declared, with the tenant made explicit.
   - Django 5.2 cannot model a composite foreign key. The ORM keeps its
     single-column key for joins, and the composite key is added in SQL.
4. **Plain-id references get a check, installed by the context that already
   depends on the other one.** This puts no new edge in the dependency graph
   (ADR-0002). There is precedent: governance and custody already install
   checks on `communities_fund` (ADR-0015).

   | Reference | Installed by | Why that side |
   |---|---|---|
   | ledger group_id, fund_id, member_id | communities | communities already uses `ledger.public`; the ledger stays the foundation and never reads communities |
   | ledger external_account_id | custody | custody already posts to the ledger |
   | custody lineresolution.journal_entry_id | custody | custody already depends on the ledger |
   | governance mandate.executed_by_line_id | custody | custody already reads mandates; governance stays independent of custody |

   Each check is a constraint trigger:
   - it reads only its own context's table;
   - it compares `tenant_id` explicitly, so a cross-tenant operation, which
     sees every row, cannot slip through;
   - it treats an invisible parent as unknown.
5. **A guard test makes the rule permanent.**
   - A catalogue test fails when any foreign key between two
     TENANT_SCOPED tables does not include `tenant_id`, unless it is listed
     as exempt with a reason.
   - One probe per relationship class (same-context key, cross-context key,
     plain id) shows the raw write refused both inside a tenant and inside
     a cross-tenant operation.

## Alternatives considered

- **Rely on RLS.** It does not apply to foreign key checks (probe above).
  Rejected.
- **One trigger per relationship** (today's pattern in communities 0009 and
  0010). This works, but there would be 30 hand-written functions, each a
  place to get the comparison wrong. A composite key is declarative and
  checked by PostgreSQL itself. Kept only for plain ids, where no key can
  exist.
- **Real foreign keys from the ledger to communities.** This would make the
  foundation depend on a higher context's tables, against ADR-0004.
  Rejected.
- **A nightly detective check instead of prevention.** It would find a bad
  row after it was written. Prevention is cheap here. Rejected as the
  primary control. The nightly ledger check (ledger 0006) remains for
  balances.

## Consequences

- **One migration per context:**
  - parents' `UNIQUE (id, tenant_id)`;
  - composite keys;
  - plain-id triggers.

  Existing rows must already comply. The migration first counts rows that
  do not, and stops if any exist. None are expected (INFERRED: every
  current write path checks in the application).
- Each new unique index costs a little storage and insert time.
- New tables inherit the rule through the guard test. A missing composite
  key fails the build, not a security review.
- Extracting a context later (ADR-0004) turns each composite key into an
  integration check. The inventory above is that work list.

## Addendum (2026-10-04): keys added under row-level security

- **The gap.** PostgreSQL checks the rows already in a table with a query
  that obeys forced row-level security. A key added with no tenant context
  was therefore checked against no rows.
  - The restore drill found this (`docs/operations/restore-drill.md`).
- **The fix.**
  - `same_tenant()` now adds each key in a cross-tenant step.
  - Tenancy migration 0002 re-adds every existing foreign key the same way.
- **The decision itself is unchanged.**
