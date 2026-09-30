# ADR-0014: Treatment of outstanding balances after membership ends

- **Status:** **Direction decided, details open.**
  - Harry decided (2026-09-30) that each group chooses, in its constitution
    at onboarding, between `SHARES_UNTIL_PAID` and `FROZEN_AT_LEAVING`, with
    no universal behaviour.
  - The model and the remaining decisions are in
    [the design](../architecture/design-leaver-balance-policy.md).
  - Not implemented yet. Raised by the membership review
  (2026-09-30); see
  [the review](../architecture/review-communities-membership.md), sections
  E and F.

## Question

> Does an unpaid balance of a leaver continue participating in
> interest/return calculations until settlement?

## What the code does today (CONFIRMED, not decided)

- Custody's `sharing_facts` shares interest, bank charges and pro-rata
  payouts among **active** members only. So when a member leaves:
  - their balance stops earning interest and bearing charges;
  - the interest their money earns goes to the others.
- Nobody chose this. It follows from reading membership status.
- `custody/tests/integration/test_returning_member.py::LeaverSharingTests`
  pins it, so a decision has to change that test deliberately.

## Options put to Harry

| Option | Consequence |
|---|---|
| **Each group decides (chosen by Harry)** | A constitution rule, beside the existing `interest` and `bank_charges` rules. Each group picks at onboarding. |
| Shares until paid | One rule for every group: money in the pool earns and bears charges until the leaver is paid out. |
| Frozen at leaving | One rule for every group: today's behaviour becomes the written policy. |

## Settled regardless of the answer

- **Not a membership property.** Communities records only that the spell
  ended. Nothing like `interest_eligible` goes on `Membership`.
- **The balance stays on the old spell.** It is keyed by membership id. A
  returning person's new spell starts at zero and inherits nothing
  (CONFIRMED, tested).
- **Settlement exists as a path:**
  1. a governed withdrawal charged to the old membership
     (`Allocation.MEMBER`);
  2. a mandate;
  3. the matched payout, which debits that member account.

## Also open (UNKNOWN)

- Whether a leaver's pro-rata share of *group spending* (not bank charges)
  should apply after leaving.
- Whether arrears owed by a leaver accrue penalties after leaving.
  Contributions and arrears do not exist in the code yet.
- Settling net of debts ("less any loan owed", pilot template §7).
- The case where every member has left. Today it raises "no active members
  to share this among".

## Owner

- The rule belongs to the group's constitution (governance), applied by the
  sharing computation.
- Once a contributions context exists, it owns obligations and arrears.
- The ledger stays the record of the postings.
