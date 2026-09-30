# Review: the membership application module

- **Date:** 2026-09-30.
- **Requested by:** Harry, "Review the newly separated membership module".
- **File:** `backend/contexts/communities/application/memberships.py`
  (plural in the code), at commit `900851a`.
- **Evidence:** code, migrations 0001–0008, triggers, tests, and probe runs
  against a real PostgreSQL 16 as `wepl_app` (the application role, which
  row-level security binds).

## A. What is correct

| Claim | Evidence | Class |
|---|---|---|
| The module holds only join (`add_member`), title (`set_title`) and leave (`leave_group`). It imports only audit and identity `public`, its own domain, models and queries. There is nothing on money, authorization, capabilities, ledger or governance. | code | CONFIRMED |
| LEFT cannot become ACTIVE. The database refuses it (trigger `communities_membership_rules`, migration 0006). | test `test_leaving_is_final_and_audited` | CONFIRMED |
| At most one ACTIVE spell per person per group. The application checks, and a partial unique index on (group, person) where active backs it. | `test_one_active_spell_per_person`; concurrent test | CONFIRMED |
| Rejoining inserts a new row; nothing updates an old one. Group, person, code and `joined_at` are immutable, and memberships are never deleted (database). | `test_repeated_leaving_and_returning`; `test_memberships_are_never_deleted_or_re_pointed` | CONFIRMED |
| Codes are never reused: M01, M02, M03; M02 leaves; the next join gets M04. | `test_leaving_keeps_the_code_…`, `test_repeated_…` | CONFIRMED |
| Each audit write is a plain insert in the same transaction as the change (`audit.public.record`). Neither can commit without the other. | code; `test_a_failed_join_consumes_no_code_and_a_retry_takes_it` (audit failure rolls the membership back) | CONFIRMED |
| `member.title_changed` records `from` and `to`, with actor, operation id and time. That is enough to rebuild every title. | code; test | CONFIRMED |
| A title grants nothing. Capabilities are governance's, and no code outside communities reads the title. | grep; `test_a_title_grants_nothing` | CONFIRMED |
| A returning member's title is not inherited: `add_member` takes `title=""` unless one is given. | code | CONFIRMED |
| `leave_group` posts nothing, notifies no one and creates nothing. It sets LEFT and writes one audit event. | code | CONFIRMED |
| `register_person` is Identity's public command (find or register by phone number). It never updates an existing person. A Person may exist with no membership (Identity owns people across all groups). If the rest of `add_member` fails, the Person insert rolls back with it (probe: "person left behind? False"). | code; probe | CONFIRMED |
| Nothing else creates memberships: no admin, management command, import or worker (grep). | grep | CONFIRMED |
| No dependency cycle: audit and identity import neither communities nor each other's internals. | architecture test | CONFIRMED |

## B. What must change

1. **A membership's tenant can differ from its group's tenant, inside a
   declared cross-tenant operation (CONFIRMED by probe).**
   - Inside a tenant, row-level security and the allocation trigger refuse
     a foreign group: "membership for an unknown group".
   - Inside `cross_tenant(...)`, every row is visible, so a raw insert with
     `group = B`, `tenant = A` **succeeded**. The row then shows in tenant A
     while belonging to group B.
   - Only WEPL's own system code can open a cross-tenant operation, and it
     is audited. But the database should make the row impossible.
   - **Fix:** the allocation trigger already reads the group row, so it also
     checks `NEW.tenant_id = group.tenant_id`.
   - The same gap probably exists for every child table (funds, capability
     changes, proposals and so on). That is INFERRED from the shared RLS
     policy, not probed, and is a wider change: see C1.
2. **No tenant context reads as "Unknown group" (CONFIRMED by probe).**
   - Safe, because nothing is written, but misleading.
   - `add_member`, `set_title` and `leave_group` should call
     `require_tenant()` first. That makes "no tenant" a `TenancyError`,
     separate from "no such group here".
3. **The query before the lock in `set_title` and `leave_group`.** The
   current code:

   ```python
   m = Membership.objects.select_for_update().get(pk=membership(membership_id).id)
   ```

   - **Harmless for correctness.** The locked `get` re-reads the row, and the
     decision (status, title) is made on the locked copy. The first query
     only turns "unknown or another tenant's" into `CommunityError`.
   - **Not a security concern.** Both queries run under the same tenant's
     RLS.
   - **Wasteful and muddled.** It does a full view read, including an Identity
     lookup of name and phone, just to get an id it already has, then
     queries again.
   - **Fix:** resolve and lock once:

     ```python
     m = Membership.objects.select_for_update().filter(pk=membership_id).first()
     if m is None:  # unknown, or another tenant's
         raise CommunityError(...)
     ```

     Return the view at the end, as now.
4. **Titles of spells that have ended can still be changed (CONFIRMED).**
   - `set_title` accepts a LEFT membership, which rewrites how a historical
     spell reads. The audit trail keeps the old value, so nothing is lost.
   - No evidence says an ended spell's label may change.
   - **Proposed:** refuse it, "this membership has ended". That is INFERRED
     from "historical records remain intact". Say if you want it allowed.
5. **The `leave_group` docstring misstates the boundary.**
   - It says settling the balance "is a separate, ledger matter".
   - Per ADR-0014 and the leaver design: the *policy* is the group's
     constitution (governance), the *calculation* is the sharing computation
     (custody now, contributions later), and the *ledger* only records the
     postings.
   - Reword it to say that. It is a comment-only change.

## C. What needs investigation

1. **Tenant consistency of every child row.** Should every tenant-scoped
   table carry a composite foreign key `(parent_id, tenant_id) →
   parent(id, tenant_id)`? That would make "child in the same tenant as its
   parent" a database fact everywhere, rather than a per-trigger check.
   Affects all contexts: ADR.
2. **`Membership.left_at`.** The leaver design needs the moment a spell
   ended; today only the audit event has it. Adding it belongs with the
   leaver-policy implementation, not this review. Set it only in
   `leave_group`, immutable, and NULL if and only if ACTIVE.

## D. ADRs required

1. **Tenant consistency across parent and child tables** (C1).
2. **ADR-0014 follow-ups**, already listed in the leaver design: which
   constitution version governs a leaver, what "paid" means, netting, and
   changing the policy. `leave_group` itself needs no ADR: it owns no
   financial rule.

## E. Membership lifecycle

```text
Person John (identity, one row, found by phone number)
  ↓ add_member
Membership #31  M07  ACTIVE     title ""       counter 6 → 7 (inside the insert)
  ↓ set_title("Treasurer")      audit: from "" to "Treasurer"
  ↓ leave_group
Membership #31  M07  LEFT       audit: member.left {code: M07}
  │  PostgreSQL: never ACTIVE again, never deleted, code and person fixed
  ↓ add_member (same phone)     same Person; title "" (not inherited)
Membership #44  M08  ACTIVE     counter 7 → 8; M07's balance, grants and history stay on #31
```

## F. Member-code integrity

This is exactly what happens, CONFIRMED by migrations 0006–0008 and tests.

1. `add_member` runs `SELECT … FOR UPDATE` on the group row. Under READ
   COMMITTED the locked read returns the latest committed
   `last_member_sequence`, so a second joiner waits, then sees the first
   joiner's increment.
2. It formats `member_code(counter + 1)` (domain).
3. It inserts. The `BEFORE INSERT` trigger `communities_membership_allocate`:
   - runs `UPDATE communities_group SET last_member_sequence = last_member_sequence + 1 … RETURNING`,
     which takes, or already holds, the same row lock;
   - refuses the row unless its code is the format of the new number.
4. `communities_group_sequence_rises` refuses any other change to the
   counter: by hand, down, or by more than 1, and a new group must start
   at 0.
5. `(group, member_code)` is unique. Memberships cannot be deleted, and
   codes cannot change.

**The lock is not what guarantees correctness; the trigger is.** If a
future path skips the `FOR UPDATE`, two joiners can compute the same code.
The trigger then makes the second fail loudly, with no duplicate. So the
invariant never depends on a developer remembering the lock; the lock only
keeps legitimate joins from failing.

**Rollback:** the increment is part of the same transaction. If the insert
or the audit write fails, both roll back, and the next join takes that same,
never-committed number, so no committed code is skipped or reused. Tested:
failed join then retry, and refused insert then counter unchanged.

**Concurrency:** tested with real connections:
- eight different people joining at once;
- the same person joining eight times at once;
- the same membership left eight times at once.

## G. Tenant isolation

| Case | What happens | Class |
|---|---|---|
| Group in the current tenant | Found and locked | CONFIRMED |
| Group does not exist | `filter().first()` is None → "Unknown group" | CONFIRMED |
| Group in another tenant | RLS `USING` hides the row, including from `FOR UPDATE`, so the same "Unknown group" with nothing written. A raw insert naming that group is refused by the allocation trigger, which cannot see it either. | CONFIRMED (probe) |
| No tenant context | Every row is hidden, so "Unknown group". Safe, but see B2. | CONFIRMED (probe) |
| Invalid tenant id | `tenant(id)` refuses to enter: "Unknown tenant" | CONFIRMED (test) |
| Inside a declared cross-tenant operation | Everything is visible, and a mismatched tenant can be written. See B1. | CONFIRMED (probe) |

**The final boundary is PostgreSQL.**
- RLS decides what `filter(pk=…)` can see.
- The stamp trigger and `WITH CHECK` decide what can be written.
- The application check only turns "invisible" into a clear error.

## H. Financial boundary

`leave_group` owns exactly one fact: *this spell ended*. It does **not**:
- freeze or continue interest or charges;
- settle, pay out, or compute an amount;
- post to the ledger;
- change capabilities. Governance reads the status and treats a LEFT spell
  as holding none.

All CONFIRMED by code.

**But the fact is read elsewhere.** Custody's sharing reads *active*
members, so today a leaver's balance is frozen as a side effect.
- That is not `leave_group` hard-coding a policy. It is custody reading a
  status, pinned by `LeaverSharingTests`.
- Where the treatment belongs is already decided and designed: the
  per-group constitution rule (governance), applied by the sharing
  computation, recorded by the ledger (ADR-0014; design doc). Classed as
  CONFIRMED direction, not yet implemented.
- When that lands, custody asks "who holds a balance, and what does this
  group's constitution say" instead of "who is active".

## I. Tests required

Already present (CONFIRMED):
- **Joining:** first membership; existing person under another name; a
  duplicate active membership refused by the application and the database;
  unknown group.
- **Codes:** M01..M03, then a leave, then M04; M100; direct inserts must
  take the next code.
- **Concurrency:** simultaneous joins; failed join, then retry; refused
  insert leaves the counter; concurrent leave; same-person concurrent join.
- **Leaving:** ACTIVE → LEFT; leaving twice refused; LEFT → ACTIVE refused.
- **Returning:** a new spell, a new code, the old spell kept, the balance
  not inherited; payments quoting an old code are held.
- **Titles:** normalisation, empty, None, maximum length, change, audit, no
  authority.

To add:
1. A known **foreign group id**: `add_member` refuses and writes nothing
   (no membership, no Person, counter unchanged in both groups).
2. A **raw insert naming a foreign group** is refused inside a tenant.
3. **Tenant mismatch inside a cross-tenant operation** is refused (B1).
4. **No tenant context** gives `TenancyError` (B2).
5. **Leaving posts nothing:** journal entries, statement resolutions and
   outbox messages are unchanged by `leave_group`.
6. **Leaving changes no grant history:** capability-change rows are
   unchanged; only what they read as changes.
7. **A LEFT spell's title** cannot be changed, if B4 is accepted.
8. **A returning member's title** starts empty unless given.

## J. Verdict

**Ready to stay as the dedicated membership module, after the five small
changes in B.**
- Its boundary is right, and its integrity rests on PostgreSQL rather than
  on developer discipline.
- The one real hole (B1) is outside the normal path: it needs a declared,
  audited cross-tenant operation. It should still be closed in the
  database.
- Nothing in it owns money, authority or policy.
