# ADR-0025: Moving a pay-in to the fund it was meant for

- **Status:** **Proposed** (Claude, 2026-10-06), built behind it. Harry
  asked to continue the agreed plan ("Continue", 2026-10-06); this is the gap
  ADR-0023 and ADR-0024 left open.
  - CONFIRMED (Harry, on a card, 2026-10-06): "One corrector". One member
    granted `correct_records` may move a pay-in; two are not needed.
  - The rest is Claude's design, as built.
- **Touches:** ADR-0022 (arrears count pay-ins), ADR-0023 (one account holds
  the group's funds), ADR-0024 (moving money between funds), ADR-0015
  (closing funds), ADR-0011 (capabilities).

## Context

- A pay-in goes to the fund whose code is in the reference, else to the
  default fund (ADR-0023). A member who pays for welfare and leaves out
  `WEL` lands in the default fund.
- Arrears and fines paid count **bank pay-ins by the fund they are in**
  (`custody.member_pay_ins`, ADR-0022), not journal entries. A fund
  transfer (ADR-0024) moves the money but not the pay-in, so the member
  stays in arrears in the fund they meant to pay. ADR-0024 recorded this as
  a separate correction, not built.

## Decision

1. **A custody correction, `move_pay_in(line, fund, by, reason)`.** It books
   the pay-in in the right fund as if it had arrived there. The bank line
   stays as it is (statement lines are facts); the correction is new rows.
2. **Two entries, one per fund's books** (as `payout_explained_elsewhere`),
   both caused by the statement line:
   - wrong fund, `pay_in_moved_out`: Dr whoever the pay-in credited (the
     member, the group for a fine, or unattributed) / Cr its cash at the
     account;
   - right fund, `pay_in_moved_in`: Dr its cash at the same account / Cr the
     member, or the group if the right fund is the one the group named for
     fines, or unattributed if the payer is still unknown.

   The account's total does not move, so reconciliation is unaffected.
3. **Two resolutions.** `moved` with the first entry, then the line's
   outcome as it was (`attributed` or `unattributed`) with the second. The
   line's fund is the fund of its latest resolution, so an unattributed
   pay-in moved to welfare is attributed there afterwards, and it can move
   again (or back).
4. **Arrears follow the line.** `member_pay_ins` counts a line only by its
   latest resolution, so a moved pay-in counts in the right fund and no
   longer in the wrong one. Moved into the fines fund it pays fines; moved
   out of it, it is a contribution again.
5. **Who.** CONFIRMED (Harry, 2026-10-06): one member granted `correct_records`, and never the
   member whose pay-in it is (as `attribute_payment`). A reason is
   required and audited (`custody.pay_in_moved`, with both funds).
6. **When it may move.** Only a pay-in whose latest resolution is
   `attributed` or `unattributed` (not opening balances, interest, charges
   or payouts). The right fund must be another open fund of the group, in
   the account's currency; it is locked against closing until the
   correction commits (`communities.hold_open_fund`). The money must still
   be there: what the pay-in's owner holds in the wrong fund, and that fund's
   cash less what is promised out of it (issued mandates, approved
   transfers), must each cover it. This is the same check as a fund
   transfer (`governance.shortfall`). If it was spent, the group decides a
   fund transfer instead.
7. **PostgreSQL holds the pair** (custody 0009): at commit, a `moved`
   resolution must be on a pay-in and be followed at once by an
   `attributed` or `unattributed` resolution for the same member, so money
   is never taken out of one fund without being booked in another.

## Alternatives

- **A fund transfer (ADR-0024).** Moves the money but not the pay-in, so
  arrears stay wrong; and it needs a vote for what is a clerical fix.
  Rejected for this case.
- **Reverse the receipt and post it again.** Reversing is the ledger's undo
  for a wrong entry, but the pay-in's original entry stays true for the day
  it was booked; the move is a later decision, so it is a new entry.
  Rejected.
- **Two correctors, as for opening balances.** Rejected (Harry chose one
  corrector, 2026-10-06): the money
  keeps its owner, the trail shows who moved it and why, and a member who
  disagrees can ask for it back.

## Consequences

- Interest or charges already split by fund balance (`by_fund_balance`)
  while the pay-in sat in the wrong fund are not re-split. The amounts are
  small; the group can move them with a transfer if it cares.
- The member is not notified of the move. Their statement shows it in both
  funds.
- Not covered: a pay-in credited to the wrong **member**. That is a
  different correction, not built.
