# ADR-0013: Founding a group

- **Status:** Proposed. Follows Harry's "Review: Communities Application
  Layer" (2026-09-30). The evidence is in
  [the review](../architecture/review-communities-application.md).
- **Amends:** ADR-0010's implementation notes (how a group gets its tenant),
  ADR-0009 (onboarding), and ADR-0012 section 1 (`Segment`).

## Decisions

### 1. A group founds its own tenant

The group *is* the tenant (ADR-0010). Founding is therefore one operation,
`communities.create_group(name, actor)`, and it runs **outside any tenant**.
In one transaction it:

1. asks tenancy to establish the group's tenant identity
   (`provision_tenant`; tenancy owns that table and audits it);
2. enters that tenant;
3. creates the group;
4. commits.

- If any step fails, nothing remains: no tenant without its group.
- Calling it from inside a tenant is refused. A group is never created
  within another boundary.
- The returned `GroupView` carries `tenant_id`. That is the group's own
  tenant identity, which callers use to act for it.
- **Physically:** `tenancy_tenant` and `communities_group` are two rows kept
  1:1 by a unique constraint.
- **Not done:** making the group's id *equal* its tenant id. It would make
  the identity literal, but it is a migration across every foreign key to a
  group, for a fact the 1:1 constraint already enforces. That is an
  ASSUMPTION to revisit if the two ids ever cause confusion.
- `provision_tenant` stays public in tenancy, but a tenant without its group
  cannot commit: a deferred check in `communities 0008` refuses it. Only
  group founding calls it.
- Only joining a member moves `last_member_sequence` (`communities 0008`):
  it starts at 0 and cannot be changed by hand, so no code is skipped.

### 2. Funds are opened separately

- A group may exist with **no** fund. This is INFERRED: Group Life groups
  organise before they collect money.
- A group may have **several** funds. This is CONFIRMED by the constitution
  template's §3 and the strategy doc.
- `open_fund(group_id, name, currency, actor)` is its own audited use case,
  with names unique per group.
- Pilot onboarding opens a fund because every pilot group already holds
  money. That is an onboarding step, not an invariant.
- Communities keeps owning funds for now. A fund names a pool of money; the
  ledger owns its balances. This is revisited when goals arrive.

### 3. `Segment` is not part of the core

- Its only use was the pilot's comparison of segments (V5).
- It is recorded per group in the pilot tracker, and no rule read it.
- It is removed from the model and from `create_group`, and existing values
  are dropped (migration `communities 0007`).
- If a fund, goal or contribution programme later needs a category, the
  context that owns that workflow adds one.
- This replaces ADR-0012 section 1.

### 4. The database allocates member codes on every insert

ADR-0012 made codes come from `Group.last_member_sequence` under the group
row lock, but only `add_member` took that path. Now a `BEFORE INSERT`
trigger on `communities_membership`:
- increments the group's counter with `UPDATE … RETURNING`, which takes
  that row lock;
- refuses the row unless its code is the one that number formats to.

So an admin tool, a worker or raw SQL cannot skip, reuse or reorder a code.

- `member_code(sequence)` in the domain stays the formatter. The trigger
  only checks its output: M01..M99, then M100 and up.
- `add_member` still locks the group first and computes the code the
  trigger will expect.
- A rollback undoes the increment together with the membership, so no code
  is ever issued twice.
- Tests:
  - direct inserts with wrong codes are refused;
  - M100 comes after M99;
  - eight different people join at once;
  - the same person joins eight times at once and gets exactly one
    membership (`tests/test_concurrency.py`).

### 5. The Identity contract

`identity.register_person(msisdn, name)` is Identity's public command: find
the person with this number, or register them.

- Communities calls it when enrolling a member, because in the pilot a
  person enters WEPL only by joining a group (STRONGLY INFERRED).
- Communities never writes or updates a `Person`.
- An existing person's name is never changed by joining (tested).
- **Revisit when login lands:** people register themselves, and
  `add_member` should take an existing person's id.

## Cross-context dependencies of communities

| On | For | Kind |
|---|---|---|
| Audit (`record`) | an audit record for each business action | command (append-only) |
| Identity (`register_person`, `people`) | enrolling a person; showing names and numbers | command; query |
| Tenancy (`provision_tenant`, `tenant`, `current_tenant`) | founding the group's tenant; acting in it | command; context |

- None of the three imports communities, so there is no cycle.
- The architecture test enforces that only `public` and `contract` are
  imported.

## Consequences

- Tests found groups with `act_for_new_group(self)`. `Scenario` founds its
  group itself. `act_for_new_tenant` is left for tests that need a bare
  tenant (the ledger and outbox tests).
- The demo founds its group, and the neighbouring group, with `create_group`.
