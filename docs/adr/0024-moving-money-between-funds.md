# ADR-0024: Moving money between a group's funds

- **Status:** **Accepted** (Harry, 2026-10-05: "Go", on the recommendation in
  the "moving money between funds" thread). Two points were Claude's
  proposals and are built as proposed: transfers use the group's payout
  approval tiers, and moves that turn members' money into the group's are
  out of scope.
- **Touches:** ADR-0002 (contexts), ADR-0003 (ledger), ADR-0014 (leavers),
  ADR-0015 (closing funds), ADR-0022 (decided like a payout), ADR-0023 (one
  account holds the group's funds).

## Context

- A group keeps several funds at its one bank account (ADR-0023), and
  decides from time to time to move money between them, e.g. 10,000 from
  General to Welfare.
- ADR-0023 accepted that this was not built. A fund holding money could only
  be emptied by paying it out of the bank, so it could not close (ADR-0015).
- A journal entry touches one fund only, in the domain and in PostgreSQL
  (CONFIRMED: `ledger/domain/journal.py`, ledger 0005). Custody already books
  one cross-fund case as two entries (`payout_explained_elsewhere`).
- Arrears count bank pay-ins by the statement line's fund, not journal
  entries (CONFIRMED: `custody/application/reports.py::member_pay_ins`).

## Decision

1. **A fund transfer is its own operation.** It moves money from one fund's
   books to another's at the same bank account. It is not income, a
   contribution, an expense or a withdrawal. Nothing reaches the bank and
   there is no statement line, so reconciliation is unaffected.
2. **It keeps ownership.** The money comes from one of
   (`governance.contract.TransferFrom`):
   - `pro_rata`: the members who would share a pro-rata payout under the
     group's leaver choices (ADR-0014), by their balances in the source fund
     when it is booked;
   - `member`: one member's own balance;
   - `retained`: the group's own money in the source fund.

   The destination credits exactly the same owners and amounts. Unattributed
   money never moves. Moving members' money into the group's ownership is out
   of scope.
3. **Who owns what.**
   - **Governance** owns the decision: `FundTransfer` and its votes, states
     OPEN → APPROVED → BOOKED, or REJECTED, CANCELLED, FAILED;
     `propose_fund_transfer`, `decide_fund_transfer`, `cancel_fund_transfer`,
     and `settle_fund_transfer` (custody reports the outcome).
   - **Custody** owns the accounting decision (`accounting.fund_transfer`)
     and the booking (`book_fund_transfer`), as for every other money event.
   - **Ledger** owns the rule that a move is a mirrored pair
     (`ledger.domain.transfer.FundTransfer`) and posts it with
     `post_transfer`. No single entry ever spans two funds.
   - **Communities** is not involved; funds hold no balance.
4. **Accounting.** Two entries in one transaction, both caused by
   `governance.fund_transfer:<id>`, keys `fund_transfer:<id>:out` and `:in`:
   - source fund, `fund_transfer_out`: Dr the owners' accounts, Cr the source
     fund's `custody_cash` at the account;
   - destination fund, `fund_transfer_in`: Dr the destination fund's
     `custody_cash` at the same account, Cr the same owners' accounts.

   Example: General holds 100,000 (A 60,000, B 30,000, C 10,000). Moving
   10,000 pro rata: General Dr A 6,000, B 3,000, C 1,000 / Cr cash 10,000;
   Welfare (20,000 before) Dr cash 10,000 / Cr A 6,000, B 3,000, C 1,000.
   The account holds 90,000 + 30,000 = 120,000, as before, and each member's
   total is unchanged.
5. **Rules.**
   - Same group, same currency, same bank account; two different funds.
   - Both funds open when proposed and when booked; a database trigger refuses
     a transfer naming a closed fund (governance 0009). Neither fund can close
     while a transfer naming it is open or approved but not booked.
   - The amount is positive. It is at most what the chosen owners hold in the
     source fund, and at most the source fund's cash less what is already
     promised out of it (issued mandates, approved transfers not yet booked)
     (`governance.contract.shortfall`). Checked when proposed, generously for
     pro-rata (every member with money counts); checked exactly when booked,
     under the lock of the group's bank account. If it fails then, the
     transfer is FAILED, nothing posts and the group is notified.
   - Decided under the group's payout tiers for the amount, as waivers are.
     The proposer, and for `member` the member whose money it is, cannot
     approve unless the constitution allows self-approval.
   - Proposal retries use a `request_key`. Booking is idempotent: the
     transfer moves APPROVED → BOOKED once, and the ledger keys replay.
   - Once approved, the caller that recorded the final vote books it with
     `custody.public.book_fund_transfer`; the nightly run
     (`book_fund_transfers`) books any approved transfer still unbooked.
   - Audited and notified like a payout.
6. **No reversal.** A transfer's entries are never reversed (the ledger and
   PostgreSQL refuse). A transfer the group regrets is undone by a new
   transfer back, decided the same way.
7. **Integrity at three layers.** The domain builds only a mirrored pair.
   PostgreSQL checks at commit that each transfer has exactly one out and one
   in entry, between two funds of one group, moving only owners' money out of
   one bank account, and that the halves mirror line for line (ledger 0009).
   The nightly `check_books` counts unpaired halves per fund
   (`unpaired_transfers`), in case a rule was bypassed.

## Alternatives

- **One entry spanning two funds.** No pair to keep together, but it breaks
  the one-fund rule that the domain, PostgreSQL, the per-fund trial balance
  and fund closing all rely on. Rejected.
- **A withdrawal plus a contribution.** Needs a bank movement that never
  happens, and would distort arrears and reconciliation. Rejected.
- **Let any context post cross-fund drafts.** Loses the group's decision and
  the ownership rule. Rejected.
- **Communities owns it.** Funds hold no balance by design. Rejected.
- **A new `treasury` context.** Premature for one use case; revisit if more
  internal movements arrive (for example loans from a fund).

## Consequences

- Funds can be wound down and closed without money leaving the bank.
- ADR-0023's "no way to move money between funds" is resolved here.
  ADR-0015's closing rule now also waits for transfers. ADR-0003 notes that
  an operation spanning funds is a set of single-fund entries under one cause.
- A pay-in that went to the wrong fund is **not** fixed by a transfer: arrears
  count pay-ins by the line's fund, so the member would stay in arrears in the
  right fund. That needs a custody correction that re-routes the line: ADR-0025.
