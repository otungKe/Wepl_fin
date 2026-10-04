# ADR-0014: Treatment of outstanding balances after membership ends

- **Status:** **Decided by Harry: every leaver rule is the group's own
  choice** (2026-09-30 for the balance rule; 2026-10-04 for the rest: "All
  those should be a group decision"). Built.
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
  - a leaver shares interest and charges only under `shares_until_paid`
    and while their balance is above zero;
  - a leaver bears a pro-rata payout made after they left only as
    `leaver_payouts` says.
- Tests: `custody/tests/unit/test_sharing.py`,
  `custody/tests/integration/test_leaver_balances.py`.

## The group's choices (each required in its constitution; no default)

| Setting | Values | Meaning |
|---|---|---|
| `leaver_balances` | `shares_until_paid`, `frozen_at_leaving` | Whether a leaver's unpaid balance keeps sharing interest and bank charges |
| `leaver_rule_version` | `at_leaving`, `current` | When the group adopts a new constitution: does a leaver keep the version in force on the day they left, or follow the one in force at each event? |
| `leaver_payouts` | `never`, `approved_before_leaving`, `always` | Whether a leaver bears a pro-rata share of a payout made after they left. `approved_before_leaving` uses the mandate's issue time (when the group's approval completed). |

- Changing any of them is a new constitution version, adopted under the
  group's own rules.
- **"Paid out" is not a setting.** Sharing is pro-rata by balance, so a
  balance of zero takes no share of anything. A settlement the officials
  record by hand, without the money reaching zero, does not exist yet.
- Constitution versions adopted before these settings existed read as
  `frozen_at_leaving`, `at_leaving` and `never`: what the software did
  while they were in force.
- **For reference, the original WEPL** paid any declared surplus to every
  member with a positive balance, so an unpaid leaver kept sharing. A leaver
  was paid out by a voted exit request, net of any advance they still owed.

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
