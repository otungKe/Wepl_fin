# ADR-0022: Contributions and arrears, as each group decides

- **Status:** **Proposed; first part built** (2026-10-04). Harry's direction
  (2026-10-04): "All those should be a group decision". Every rule below is
  a setting the group fills in; WEPL picks none of them. Harry said "Merge
  and next" without answering the four open questions; the thread built on
  the answers under "Open questions, as built" (not yet confirmed by Harry).
- **Builds on:** ADR-0014 (leavers), ADR-0015 (funds), the constitution
  template §3 (each fund has a name, a purpose and a contribution rule).

## What the original WEPL did (CONFIRMED, otungke/wepl at a7f78e2)

- Each pool set `frequency` (daily, weekly, monthly, anytime) and
  `amount_type` (`fixed` per member, or `open`) with `fixed_amount`
  (`apps/contributions/models/contribution.py`).
- Changing the amount, target, end date or voting threshold needed an
  amendment voted under the pool's own `amendment_voting_threshold`
  (`services/amendments.py`).
- **No arrears and no penalties.** Nothing computed what a member owed. The
  only lateness rule was `late_contribution_policy` (open, strict, or a
  grace period), about paying after the pool's *end date*.
- Leaving: an exit payout of the member's share less any advance owed.

## Decision (proposed)

1. **A contribution rule belongs to a fund, and lives in the constitution.**
   The constitution gets a `contributions` list, one entry per fund (by fund
   id). A fund with no entry takes any amount at any time and has no
   arrears. Changing a rule is a new constitution version, adopted under the
   group's own approval rules; each version applies from its date.
2. **What the group sets for a fund (all required when the entry exists):**

   | Setting | Values |
   |---|---|
   | `frequency` | `weekly`, `monthly` |
   | `amount` | the fixed amount each member owes per period |
   | `due_day` | weekday (1–7) for weekly, day of month (1–28) for monthly |
   | `starts_on` | the first period's date |
   | `payment_order` | `oldest_first` (a payment clears the oldest amount owed first) or `current_first` |
   | `extra_payments` | `pay_ahead` (paying more covers later periods) or `savings` (it does not) |
   | `joiners_owe_from` | `joining` (from the next due date after joining) or `start` (back to `starts_on`) |
   | `late_fine` | `none`, a fixed amount, or a percentage of the overdue amount, with `grace_days` and `pay_into` (the group-named fund fines are paid into) |
   | `leaver_arrears` | `written_off` or `deducted_from_payout` |

3. **Arrears are derived, never stored.** For each membership spell: what
   was due (periods since the group's rule says they owe, times the amount)
   minus what they paid into that fund (their ledger credits from pay-ins).
   No counter column (guideline: balances are derived).
4. **A fine is an amount owed to the group, not money moved.** It shows
   beside arrears. When it is paid, the payment is booked to the group
   (retained), not to the member's share. No fine is ever taken from a
   member's balance without a governed payout.
5. **A new `contributions` context** owns schedules, what is due and
   arrears. It reads memberships (communities), the rule (governance) and
   pay-ins (ledger) through their public surfaces, and posts nothing.

## Open questions, as built (Claude's answers; Harry has not confirmed)

1. **Per fund or whole group?** Per fund, as the template §3 has it.
2. **Paying more than is due?** A group choice, `extra_payments`.
3. **Where a paid fine goes?** DECIDED (Harry, 2026-10-05): "fines should
   be payable into a group-named fund. Until payment occurs, they remain an
   obligation/amount owed and have no effect on cash or fund balances."
   Built: each fine rule names `pay_into`, an open fund of the group with no
   contribution rule of its own (so a pay-in there is plainly a fine). A
   member's pay-in to it is booked as the group's money in that fund
   (`retained`, entry kind `fine_payment`), never their share, and is set
   against their fines from every rule naming that fund, oldest first.
   Proposed, not confirmed: paying more than all fines owed stays in the
   fines fund as the group's and is shown as `fines_beyond`; returning it
   is an ordinary approved payout.
4. **Waivers?** Not built. Proposed: approved like a payout, under the
   group's own approval rules.

## How it works (built)

- `governance/domain/contribution.py` parses each rule;
  `adopt_constitution` refuses a rule for a fund that is not one of the
  group's open funds, and a second rule for the same fund. Every setting
  is required.
- `contexts/contributions` (stores nothing, posts nothing):
  - `domain/schedule.py`: due dates (weekly by weekday, monthly by day
    1–28). Each due date takes the rule in the constitution version in
    force that day; the first version also covers earlier dates, so a group
    onboarding with an existing rule can be owed back to `starts_on`.
  - `domain/standing.py`: a payment counts for every period that has begun
    (the period up to a due date begins the day after the previous one), so
    paying a few days early is on time. It clears periods in the group's
    `payment_order`; anything left is paid ahead or savings, as chosen. A
    period still owing when its grace days run out is fined once: the fixed
    amount, or the percentage of what was then owed. A leaver owes nothing
    after the day they left; `written_off` shows their arrears and fines as
    written off.
  - `member_standing`, `fund_standing` (public), and the command
    `contribution_standing --tenant T --fund F`.
- Pay-ins are the member's attributed pay-ins in that fund, dated by the
  bank (`custody.member_pay_ins`); opening balances are not pay-ins. All of
  a member's pay-ins into a fund count towards its rule: there are no
  other kinds of pay-in yet.
- The payment order, extra-payment, fine and leaver settings used are those
  in force on the day asked about.

## Alternatives

- **A WEPL default schedule.** Rejected: Harry's direction is that the
  group decides.
- **Arrears as a stored balance updated on each payment.** Rejected: a
  mutable money counter, which the guidelines forbid.
