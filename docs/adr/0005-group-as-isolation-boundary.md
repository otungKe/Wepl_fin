# ADR-0005: The group is the data-isolation boundary, for now

- **Status:** Proposed; **open question** (2026-09-30)

## Context

Rule 23 makes tenancy a security boundary. The tenancy model is not yet
decided (UNKNOWN). The candidates include:
- each group as its own tenant;
- institutions (for example I&M, or a SACCO serving many groups) as tenants
  over their groups (INFERRED from the strategy document's "institutions as a
  second customer").

Deciding this now would be inventing a requirement (rule 56).

## Decision

Until tenancy is decided, **the group is the isolation boundary**:
- Every business command identifies the group it acts in and verifies that
  every referenced record (member, fund, mandate, statement line) belongs to
  that group. A mismatch fails.
- Every audit record carries the group id.
- `tests/test_isolation.py` proves that cross-group attribution, explanation,
  proposals, votes and mandate matching all fail.

## Open question for Harry

Who is the tenant: the group, or an institution that serves many groups?
That answer decides where the tenant id lives, and whether PostgreSQL
row-level security is added.

## Consequences

When tenancy is decided, a `tenancy` context sets the tenant for each
operation, the same way `audit.operation` does today. The group checks
remain as a second layer.
