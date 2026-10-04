# ADR-0014: Treatment of outstanding balances after membership ends

- **Status:** **Direction decided; built on recommended details that
  Harry has not yet confirmed.**
  - Harry decided (2026-09-30) that each group chooses, in its constitution
    at onboarding, between `SHARES_UNTIL_PAID` and `FROZEN_AT_LEAVING`, with
    no universal behaviour.
  - Built 2026-10-04 on the three details recommended to Harry on
    2026-10-04 (see "Details built" below). If he answers differently, the
    rule changes in one place: `custody/domain/sharing.py`.
  - The model is in
    [the design](../architecture/design-leaver-balance-policy.md). Raised by
    the membership review (2026-09-30); see
    [the review](../architecture/review-communities-membership.md), sections
    E and F.

## Question

> Does an unpaid balance of a leaver continue participating in
> interest/return calculations until settlement?

## What the code does (CONFIRMED, tested)

- **The choice is required.** `adopt_constitution` refuses a constitution
  without `leaver_balances` (`shares_until_paid` or `frozen_at_leaving`).
  There is no default.
- **Leaving records when.** `Membership.left_at` is set by `leave_group`.
  The database refuses to change it once set, and requires it exactly when
  the status is `left` (communities migration 0014). Existing leavers were
  given the time of their `member.left` audit record.
- **Sharing is judged on the event's date** (`StatementLine.posted_at`),
  not the day the statement arrived (`custody/domain/sharing.py`):
  - a member in the group that day shares interest, bank charges and
    pro-rata payouts;
  - a member who joined after the event shares nothing from it;
  - a leaver shares interest and charges only if the rule in force on the
    day they left was `SHARES_UNTIL_PAID` and their balance is still above
    zero;
  - a leaver never shares a pro-rata payout made after they left.
- Tests: `custody/tests/unit/test_sharing.py`,
  `custody/tests/integration/test_leaver_balances.py`.

## Details built (recommended, awaiting Harry's confirmation)

1. **Which version of the rule:** the one in force on the day the member
   left. A later change does not reach back to earlier leavers.
2. **"Paid out" means the balance reaches zero.** A leaver with nothing
   left stops sharing.
3. **Group spending after leaving:** a leaver is excluded from every
   pro-rata payout dated after they left. (Simplification: the payout's
   date is used, not the date it was approved. A payout approved before
   they left but paid after does not reach them.)

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

- Whether arrears owed by a leaver accrue penalties after leaving.
  Contributions and arrears do not exist in the code yet.
- Settling net of debts ("less any loan owed", pilot template §7).
- The case where nobody shares an event (every member has left under
  `FROZEN_AT_LEAVING`). It still raises "no active members to share this
  among".

## Owner

- The rule belongs to the group's constitution (governance), applied by the
  sharing computation.
- Once a contributions context exists, it owns obligations and arrears.
- The ledger stays the record of the postings.
