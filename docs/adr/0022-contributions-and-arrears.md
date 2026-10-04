# ADR-0022: Contributions and arrears, as each group decides

- **Status:** **Proposed** (2026-10-04). Not built. Harry's direction
  (2026-10-04): "All those should be a group decision". Every rule below is
  a setting the group fills in; WEPL picks none of them.
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
   | `joiners_owe_from` | `joining` (from the next due date after joining) or `start` (back to `starts_on`) |
   | `late_fine` | `none`, a fixed amount, or a percentage of the overdue amount, with `grace_days` |
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

## Open (UNKNOWN), for Harry

- Should a rule be per fund (as the template §3 suggests) or one for the
  whole group?
- Is a fine booked as group income, or held for a purpose the group names?
- Who may waive arrears or a fine for one member, and how is that approved?
- Does a member's pay-in that exceeds what is due count as paid in advance
  for future periods, or only as savings?

## Alternatives

- **A WEPL default schedule.** Rejected: Harry's direction is that the
  group decides.
- **Arrears as a stored balance updated on each payment.** Rejected: a
  mutable money counter, which the guidelines forbid.
