# Review: Communities membership, and what a leaver's money does

- **Date:** 2026-09-30.
- **Requested by:** Harry, "Review the updated groups.py and the related
  Communities membership implementation".
- **Code reviewed:** commit `056c72f`, plus a probe run against it.
- **Classes used:** CONFIRMED means established by code, tests, migrations,
  a probe run, or an explicit decision by Harry.

## A. Current model

| Concept | What the code holds | Where |
|---|---|---|
| Group | name; `last_member_sequence`; its own `tenant_id` (unique) | `communities_group` |
| Tenant | one row per group; the row-level security boundary | `tenancy_tenant` (owned by tenancy) |
| Fund | a group's named pool: name and currency; 0..n per group | `communities_fund` |
| Person | phone number and name, one per phone number | `identity_person` |
| Membership | one spell: group, person, status (ACTIVE or LEFT), member code, title, joined_at | `communities_membership` |
| Capability | append-only grants per membership | `governance_capabilitychange` |
| Balance | the sum of journal lines on the member account, keyed `(fund_id, member_id = membership id)` | ledger |

**Contributions and arrears do not exist in the codebase (CONFIRMED).**
- There is no `contexts/contributions` and no model or rule for an
  obligation, a due amount, a penalty or arrears.
- "Contribution" today means only a statement pay-in attributed to a
  member. Custody posts it as a receipt, and a `contribution.received`
  notification is queued.
- The pilot tracker's "Obligations" sheet (due, paid, penalty, arrears) is
  the only place those concepts exist, and it is outside the code.

## B. Correct decisions to retain

All CONFIRMED by code and tests unless marked otherwise.

- **Group is the tenant.**
  - `create_group` runs outside any tenant and, in one transaction:
    1. calls tenancy to create the tenant row, audited;
    2. enters it;
    3. creates the group;
    4. writes the audit event.
  - A failure leaves neither behind (`test_a_failed_founding_leaves_no_tenant_behind`).
  - It is refused inside a tenant.
  - One group per tenant is a unique constraint.
- **Funds are separate from founding.**
  - A group can have no fund or several. A duplicate name is refused.
  - The ledger stores `fund_id` as a plain number with no foreign key. It
    keeps balances and never reads the `Fund` row.
  - Communities never holds an amount. This matches "a fund names a pool;
    balances are the ledger's".
- **Membership spells.**
  - Rejoining inserts a new row with a new code.
  - PostgreSQL refuses LEFT → ACTIVE, deleting a membership, and changing
    its group, person, code or joining time.
  - A partial unique index allows one ACTIVE spell per person per group.
  - Identity is found by phone number and not duplicated on return. The
    name is not overwritten.
- **Title is a label.**
  - It is optional, per membership (so per group), and normalised to "" for
    none. Changes are audited from → to.
  - No code outside communities reads it; checked by grep.
  - Authority is capabilities only (ADR-0011).
- **`Segment` is gone.**
  - It survives only as history in migrations 0001 (literal choices) and
    0007 (its removal).
  - Nothing in code or docs uses it except the ADRs recording its removal.
  - The evidence (ADR-0013 and the earlier review):
    - it was recorded once per group, for the pilot's segment comparison;
    - one group runs savings and welfare together as two funds;
    - no rule read it.
  - Class: CONFIRMED.
- **Dependencies are all through `public` and there are no cycles.** Audit,
  identity and tenancy import only audit.

## C. Problems

| # | Problem | Class | Severity |
|---|---|---|---|
| 1 | **Leaving silently changes the money.** Custody's `sharing_facts` shares interest, bank charges and pro-rata payouts among **active** members only. The moment a member is LEFT, their balance stops earning interest and bearing charges, and the interest their money earns goes to the others. Probe: five members with KES 1,000 each; M04 leaves; KES 100 interest and KES 10 charges arrive. M04 stays at 1,000.00 and everyone else goes to 1,022.50. This is a financial policy that nobody decided, made implicitly by reading membership status. | **CONFIRMED** | High |
| 2 | **Bare tenants are still possible.** `provision_tenant` is public, and nothing in the database requires a tenant to have its group. The "tenant containing a group" shape can still be built, just not through `create_group`. | **CONFIRMED** | Medium |
| 3 | **The member counter can be raised by hand.** The trigger stops it going down but not up, so an admin `UPDATE` can skip codes. That doesn't break uniqueness or monotonicity, but it breaks "numbered in joining order" (gaps). | **CONFIRMED** | Low |
| 4 | **Unknown group ids leak `DoesNotExist`.** `open_fund(999999)` and `add_member(999999, …)` raise Django's `Group.DoesNotExist` instead of `CommunityError`. The same happens for another tenant's group, which RLS makes invisible. | **CONFIRMED** (probe) | Low |
| 5 | **`groups.py` holds three aggregates**: group founding, funds, and the membership lifecycle. That is the drift toward a generic service layer that you warned about. | **CONFIRMED** | Low |
| 6 | **Rollback, retry and concurrent leave are not tested.** The code is right by mechanism (section G), but nothing locks it in. | **CONFIRMED** | Medium |
| 7 | **The tenant row keeps a copy of the group's name** (`Tenant.name`). It is harmless today because there is no rename, but it could drift. | **CONFIRMED** | Low; investigate |

## D. Membership lifecycle

```text
John joins                 add_member → Membership #1  M07  ACTIVE   (counter 6 → 7)
M02 (someone else) leaves  M02 stays LEFT; its code stays M02
Mary joins                 Membership #9   M08  ACTIVE               (counter 7 → 8, never back to 2)
John leaves                leave_group(#1) → LEFT                    (audited; capabilities lapse)
John leaves again          refused: "already ended"                  (app and database)
John returns               add_member → Membership #12  M09  ACTIVE  (same Person, new spell)
Anyone sets #1 ACTIVE      refused by PostgreSQL
```

Every record points at the membership id, never at the person or the code.
That includes ledger lines, statement resolutions, proposals, approvals,
grants, payer memory and audit targets. So M07's history stays M07's, and
M09 starts with a zero balance and no capabilities (CONFIRMED;
`test_returning_member.py`).

## E. Financial boundary

| Concern | Owner today | Owner it should have |
|---|---|---|
| Membership termination | Communities, `leave_group` (a status change plus audit, no money) | Communities. Correct. |
| Contribution obligation (what is due) | **Nobody.** Only the paper tracker. | A contributions context (not built) |
| Arrears | **Nobody.** | Contributions |
| Outstanding balance, entitlement | Ledger member account per membership spell; the balance is derived | Ledger holds it; contributions decides what is owed |
| Interest and charge eligibility | **Custody, implicitly** (`sharing_facts`: active members) | A rule owned by the group, stated explicitly (see F) |
| Settlement or final payout | Governance: a withdrawal with `Allocation.MEMBER` charged to the (possibly LEFT) membership, then a mandate, then the custody match debiting that member account | Governance and custody, as today; contributions would say how much is owed |
| Ledger posting | Ledger `post_journal`, the only door | Ledger. Correct. |

## F. The leaver arrears question

> Does an unpaid balance of a leaver continue participating in
> interest/return calculations until settlement?

**The codebase does not answer it by decision. It answers it by accident.**
Today the answer is *no*: the balance is frozen at leaving, earns nothing
and bears no charges (CONFIRMED, problem 1). Nothing documents or tests
that as a rule.

**ADR REQUIRED: treatment of outstanding contributions, arrears and
balances after membership ends.**

- **Who should own the decision.** The group's **constitution**, applied by
  the context that computes sharing.
  - The constitution already owns the sharing rules for interest and bank
    charges (`ConstitutionRules.interest`, `bank_charges`: CONFIRMED).
  - The pilot template's §7 asks each group for its leaving rule ("balance
    paid out within ___ days, less any loan owed").
  - So *whether a leaver shares until settled* is STRONGLY INFERRED to be a
    per-group rule, not a WEPL-wide policy and not a membership property.
  - Nothing is added to `Membership`.
- **Where it is applied.** Today, custody's `sharing_facts`. When the
  contributions context exists, it owns obligations and arrears, and the
  sharing rule reads "who holds a balance in this fund" from the ledger, not
  "who is ACTIVE" from communities.
- **Not answered anywhere (UNKNOWN):**
  - whether arrears owed *by* a leaver accrue penalties after leaving;
  - whether a leaver who owes money can be paid out net of it, as the
    template's "less any loan owed" suggests;
  - what happens if every member has left, where the code raises "no active
    members to share this among".

**Answers to your ten questions:**

1. **What entity owns the outstanding amount?** The ledger member account
   for that membership spell. It is derived from journal lines (CONFIRMED).
   An obligation or arrears entity does not exist (CONFIRMED).
2. **What does it reference?** Membership id and fund id (CONFIRMED).
3. **Does leaving create a financial event?** No. Only an audit event
   (CONFIRMED).
4. **Does leaving freeze the position?** In effect yes, for interest,
   charges and pro-rata payouts (CONFIRMED, by accident).
5. **Does interest continue?** No, today (CONFIRMED). Whether it *should*:
   ADR REQUIRED.
6. **Who decides the rule?** Nobody. It falls out of custody reading
   membership status (CONFIRMED).
7. **How is settlement represented?** A governed withdrawal charged to the
   old membership (`Allocation.MEMBER`), then a mandate, then a matched
   payout debiting that account (CONFIRMED path). Nothing ties it to the
   leave or checks it against the balance (UNKNOWN whether it should).
8. **What happens if they rejoin?** A new spell and a new zero-balance
   account (CONFIRMED).
9. **Does the old obligation stay with the old spell?** Yes, keyed by the
   old membership id (CONFIRMED).
10. **Can the new membership inherit old arrears or an entitlement?** Not
    automatically. Nothing links the spells except the shared person
    (CONFIRMED). Whether a group may *choose* to carry a balance across, by
    transfer between the accounts, is UNKNOWN.

## G. Concurrency and sequence integrity

How a code is allocated in the current code (CONFIRMED by reading the
migration and the code):

1. `add_member` locks the group row (`SELECT … FOR UPDATE`). Under READ
   COMMITTED it reads the latest committed `last_member_sequence`.
2. It formats `member_code(counter + 1)` in the domain.
3. It inserts the membership. The `BEFORE INSERT` trigger
   `communities_membership_allocate` runs
   `UPDATE communities_group SET last_member_sequence = last_member_sequence + 1 … RETURNING`.
   That takes, or re-takes, the same row lock. The trigger refuses the row
   unless its code equals the one that number formats to.
4. The counter cannot go down (trigger `communities_group_sequence_rises`).
   Memberships cannot be deleted, and codes cannot change. `(group,
   member_code)` is unique.

What that guarantees:

| Case | Result | Class |
|---|---|---|
| Two concurrent joins | Serialised on the group row. Both succeed with consecutive codes. | CONFIRMED (test, 8 threads) |
| The same person joining at once | One membership; the rest are refused | CONFIRMED (test) |
| A failed insert (constraint or trigger error) | The failed statement rolls back, including the trigger's increment. The counter is unchanged. | CONFIRMED by PostgreSQL semantics, **not tested** |
| Rollback after the insert (for example, the audit write fails) | The whole transaction rolls back, counter included. The code was never visible, so it is not "reused" when the next join takes it. | CONFIRMED by mechanism, **not tested** |
| Retry after a failure | Takes the same, never-committed number | as above, **not tested** |
| Admin or raw SQL insert | Must take exactly the next code, or it is refused | CONFIRMED (test) |
| Background creation paths | None exist | CONFIRMED |
| M02 leaves, next join | Gets the counter's next number (M04 after M03), never M02 | CONFIRMED (tests) |

**Verdict:** every *committed* sequence is unique, monotonic within the
group, and never reused. The two gaps are problem 3 (a manual increase can
create gaps) and problem 6 (the failure paths are untested).

## H. Keep / Change / Investigate / ADR required

### Keep
Everything in section B.

### Change
1. **Stop leaving from silently changing the money.** Make the sharing
   rule's participant set explicit, and pending the ADR, *keep today's
   behaviour* but name it and test it. Leaving must not change a financial
   rule without a decision behind it. Only custody's `sharing_facts` and a
   test are touched; no new policy.
2. **Every tenant has its group.** A deferred constraint trigger, owned by
   communities' migrations, refuses to commit a tenant without a group.
   Tests that need a tenant found a group instead.
3. **Only allocation may move the counter.** Refuse any change to
   `last_member_sequence` that does not come from the allocation trigger.
4. **Unknown or foreign group ids** raise `CommunityError`, like unknown
   members do.
5. **Split `groups.py`** into `groups.py` (founding), `funds.py` and
   `memberships.py`. No behaviour change.

### Investigate
- Group id equal to tenant id, and whether `Tenant.name` should exist at all.
- Whether funds move to a treasury-like context when goals arrive.

### ADR required
- **Treatment of outstanding contributions, arrears and balances after
  membership ends.** Proposed owner: each group's constitution, applied by
  the sharing rule, with contributions owning obligations once it exists.
- That ADR also covers settlement net of debts, penalties after leaving,
  and the "everyone left" case.

## I. Tests required

1. A failed membership insert leaves the counter unchanged. The next join
   takes that number (rollback).
2. An audit failure after the insert rolls back the membership and the
   counter (the transaction boundary).
3. A retry after a failed join gets the same code, once.
4. Two concurrent `leave_group` calls: one succeeds and one is refused.
5. A manual counter change outside allocation is refused (Change 3).
6. A tenant without a group cannot be committed (Change 2).
7. Unknown or foreign group ids raise `CommunityError` (Change 4).
8. **Leaver's balance and sharing:** a test that states today's behaviour
   explicitly, so the ADR's decision has to change a named test rather than
   an accident.
9. Already present: first membership, repeated leave and return, identity
   stable, no two active spells, direct-insert codes, concurrent joins, old
   codes after a return, and "a title grants nothing".
