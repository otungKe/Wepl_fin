# Review: Communities application layer

- **Date:** 2026-09-30.
- **Requested by:** Harry, "Review: Communities Application Layer".
- **Code reviewed:** `backend/contexts/communities/application/groups.py` at
  commit `fd2a106`. The snippet in the request predates two fixes; where the
  code already differs, that is noted.

## 1. Tenancy boundary: the creation order is backwards

**Today (CONFIRMED, code):** founding a group takes three separate calls.

1. `tenancy.provision_tenant(name)`.
2. Enter `tenant(id)`.
3. `communities.create_group(...)`, which calls `require_tenant()` and
   refuses a second group in that tenant.

The demo and `Scenario` both do this. It is exactly the model Harry
rejects: *create/enter a tenant, then create a group inside it*. Nothing
stops someone provisioning a tenant and never creating its group, which
leaves a tenant with no group.

**Physically (CONFIRMED):**
- `communities_group.tenant_id` is unique, so group and tenant are 1:1.
- The `tenancy_tenant` row is how row-level security names the boundary.
- Tenancy owns that table; communities must not write it (ADR-0009).

**Change:** make founding one use case that communities owns.

`create_group(name, ...)`, called with **no** tenant context:
1. asks tenancy to establish the group's tenant identity (a tenancy
   command, audited as today);
2. enters that tenant;
3. creates the group;
4. commits, all in one transaction.

- Calling it from inside any tenant context is refused, because founding a
  group from inside another group would be a scope switch.
- `require_tenant()` leaves `create_group`.
- `provision_tenant` stays in tenancy's public surface, but only group
  founding and tests call it.

**Investigate:** whether group id and tenant id should be the same number
(the group's primary key *being* its tenant id). It would make "the group is
the tenant" literal. It is a large migration touching every foreign key to
a group, and 1:1 with a unique constraint already enforces the same fact.
**ASSUMPTION** that 1:1 is enough.

## 2. Group and fund: not a domain invariant

"A group never exists without its first fund" is **not supported by
evidence**:

| Evidence | Class |
|---|---|
| Group Life (chat, announcements, meetings, vault) is part of the product. The strategy doc calls it "where the group actually lives", while "money is checked about once a month". A group can be organising before it collects money. | **INFERRED** |
| A group has several named funds, which is "core infrastructure" (strategy doc). The constitution template §3 lists "Main savings" and "(optional) Welfare". | **CONFIRMED** |
| There is **no use case to add a fund**, so today every group has exactly one fund forever. That contradicts the line above. | **CONFIRMED** (code) |
| Every *pilot* group already holds money somewhere (pilot plan, "Money:" criterion), so onboarding creates a fund every time. | **CONFIRMED**, but it is a pilot onboarding fact, not an invariant |

**Answers:**
1. Can a group exist before it has a fund? Yes.
2. Is a fund mandatory? No.
3. Is exactly one initial fund mandatory? No.
4. Can funds be added later? They must be, and today they cannot.
5. Who owns funds? See "Investigate" below.
6. Is fund creation part of group creation? No, it is its own use case.

**Change:**
- `create_group` creates only the group.
- A new `open_fund(group_id, name, currency, actor)` use case: audited,
  unique name per group.
- Onboarding (the demo and `Scenario`) calls both.

**Investigate, fund ownership:**
- Today communities owns `Fund`: a group's named pool, with a currency.
- The ledger keys accounts by `fund_id`. Governance proposes "on a fund".
  Custody links a bank account to a fund.
- A fund is where a group's money is pooled. It carries no money itself,
  since balances are the ledger's.
- **INFERRED:** communities is an acceptable owner for now. Moving it later
  is cheap while only `fund_view` is public.
- Revisit when goals and contribution programmes arrive. A goal may be a
  fund, or a target within one (**UNKNOWN**).

## 3. `Segment`: not foundational

| Evidence | Class |
|---|---|
| It is recorded once per group: the constitution cover page and the pilot tracker's Groups sheet each have one "Segment" field. | **CONFIRMED** |
| One group can run savings and welfare together, and the template does this with two funds. So a group's "segment" is at best its main character. | **CONFIRMED** |
| Its only use is comparing segments in the pilot (V5). No rule reads it, and the core is "group-type-agnostic". | **CONFIRMED** |
| It describes a fund, goal or programme. | No evidence yet; the template gives funds a free-text "Purpose" |

**Change:** remove `Segment` from the core model and from `create_group`.
- It is research metadata about the pilot. The pilot tracker already
  records it per group.
- If a fund, goal or programme later needs a category, that context adds
  one with the workflow that uses it.
- This supersedes the part of ADR-0012 that kept it on the group.

## 4. Member codes: already fixed; harden every path

**Already done (CONFIRMED, `a7f7e57`):**
- The snippet's `count() + 1` is gone.
- Codes come from `Group.last_member_sequence`, incremented under the group
  row lock.
- PostgreSQL refuses to lower the counter, delete a membership, or change
  its code.
- `tests/test_concurrency.py` runs eight joins at once, and fails if the
  lock is removed.

**Gap (CONFIRMED):** the lock protects only callers of `add_member`.
- A future admin tool, worker or raw SQL that inserts a membership directly
  could skip the counter.
- The unique `(group, member_code)` index stops a *duplicate*, but not a
  code taken out of order or a counter left behind.

**Change:** let PostgreSQL take the sequence on every insert.
- A `BEFORE INSERT` trigger on `communities_membership` increments the
  group's counter. It uses `UPDATE … RETURNING`, which takes the same row
  lock.
- It refuses the row unless its code is the one that number formats to.
- `member_code(sequence)` stays the only formatter in Python. The trigger
  checks the format; it does not choose it.

**Other cases:**

| Case | What happens | Class |
|---|---|---|
| Rollback | The counter increment rolls back with the failed membership, so no code was ever issued. | **CONFIRMED** |
| Retry after success | Refused ("already an active member"): safe, not idempotent. | **CONFIRMED** |
| Concurrent rejoin of the same person | The second caller waits on the lock, then sees the active spell and is refused. The partial unique index is the backstop. | **CONFIRMED** by design, **not yet tested**; the test will be added |

## 5. Identity boundary

`register_person(msisdn, name)` is Identity's public command. It means
"find the person with this number, or register them".

| Point | Finding | Class |
|---|---|---|
| Communities writes identity data? | No. It never touches `Person`. Identity decides what a phone number resolves to. | **CONFIRMED** |
| Can Communities change an existing person? | No. An existing person's name is never updated, even if a different name is passed. Tested by `test_a_returning_person_keeps_their_identity_even_under_another_name`. | **CONFIRMED** |
| Is "adding a member registers the person" a real rule? | In the pilot, the operator enrols people only as members of a group. There is no other way in until login exists. | **STRONGLY INFERRED** |

**Keep, and document it as the contract.** Revisit when login lands: then a
person registers themselves, and `add_member` should take an existing
person's id.

## 6. Membership versus authorization

**Keep.**
- A title is a label and never checked (ADR-0011).
- Capabilities are governance's.
- No role enum exists, and a test proves a title grants nothing.

## 7. Cross-context dependencies

| Dependency | Why | Owner | Kind | Cycle? | Exposes too much? |
|---|---|---|---|---|---|
| Communities → Audit `record` | Business actions need an audit record | Audit | command (append) | No: audit imports nothing | No |
| Communities → Identity `register_person`, `people` | Enrol a person; show a member's name and number | Identity | command; query | No: identity imports only audit | No |
| Communities → Tenancy `require_tenant` (today) / tenant founding (after the change) | A group is a tenant; RLS needs its context | Tenancy | query today; command after | No: tenancy imports only audit | `provision_tenant` should be called by group founding only |

The architecture test already forbids importing anything but
`public`/`contract` (**CONFIRMED**).

## 8. Application versus domain

**Keep:**
- Title cleaning, the leave rule and code formatting are in the domain.
- The application layer orchestrates, and the database backs each rule.

**Change:** the "one group per tenant" check moves out of `create_group`.
- Once founding creates the tenant itself, the check cannot fail except by
  a bug.
- The unique constraint stays.

## Summary

### Keep
- Title as a label.
- Capabilities in governance.
- The member-code counter and its database guards.
- LEFT being final.
- `register_person` as Identity's contract.
- Imports only through `public`.

### Change
1. `create_group` founds the tenant itself, in one transaction, and refuses
   to run inside a tenant.
2. Fund creation becomes its own use case, `open_fund`, which also allows
   several funds.
3. Remove `Segment` from the core model.
4. A PostgreSQL insert trigger makes every membership insert take the next
   sequence.
5. A concurrency test for the same person rejoining twice at once.

### Investigate
- Group id equal to tenant id.
- Fund ownership once goals arrive.
- What category, if any, funds or goals need.

### ADR required
One ADR, **ADR-0013 "Founding a group"**, covering:
- a group founds its own tenant;
- fund lifecycle;
- `Segment` removed;
- member sequences allocated by the database;
- the Identity contract.

It amends ADR-0010's implementation notes and ADR-0012 (section 1).
