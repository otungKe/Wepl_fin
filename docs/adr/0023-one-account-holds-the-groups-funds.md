# ADR-0023: One bank account holds all of a group's funds

- **Status:** **Accepted** (Harry, 2026-10-05: "Accepted").
  - CONFIRMED (Harry, 2026-10-04): a group has only one bank account.
  - CONFIRMED (Harry, on a card, 2026-10-04): "Code, else default". A member
    may add a short fund code to the payment reference; without one, the
    money goes to the fund the group named as its default.
  - ACCEPTED (Harry, 2026-10-05): everything else below, which Claude
    proposed (how interest and charges split, how an unknown code is
    treated, how an outflow explained by another fund's mandate is booked).
- **Touches:** ADR-0013 (a group has 0..n funds), ADR-0015 (closing funds
  and accounts), ADR-0019 (the collections reference), ADR-0014 (sharing).

## Context

- The code linked one custodian account to one fund, and an account number
  could be linked only once. A group with a second fund ("Welfare") had
  nowhere for that fund's money to arrive.
- Groups do keep several pools in one account. Common practice, in
  chama record keeping and in bank "virtual account" or sub-ledger
  products: one real account, and a ledger that splits it by purpose.
  WEPL's ledger already keeps each fund's books apart.

## Decision

1. **The account holds all of the group's funds.** Each fund keeps its own
   books, including its own cash at the account (`custody_cash` keyed by
   fund and account). The account's balance is the sum of its funds' cash.
   `ExternalAccount.fund` is the **default fund**. A ledger cash account
   may name any account of its own group (custody 0008; it used to have to
   be the same fund's).
2. **Fund codes.** A fund may have a code of 2 to 6 letters (`WEL`), unique
   among the group's open funds, case ignored (communities 0015;
   `open_fund(code=…)`, `set_fund_code`, audited). Letters only, so a code is
   never read as a mobile number or a member code (`M01`).
3. **A pay-in goes to the fund its reference names, else to the default
   fund** (`custody/domain/routing.fund_for`). The code is taken out before
   the rest of the reference names the member (ADR-0019), so
   `0712597024 WEL`, `WEL 0712597024` and `M05 WEL` all work.
   - Letters that are no open fund's code are ignored and the
     money goes to the default fund (it still belongs to the member and is
     visible). Where the collections service is on, the bank's reference
     check refuses such a reference instead (`/collections/validate`), so
     the payer can correct it before paying.
4. **A payout spends the fund its mandate names.** Mandates are matched
   across all of the group's funds (`find_by_reference`, `issued_for_amount`
   take the group). An outflow nobody can match is held as unexplained in
   the default fund until explained.
5. **Interest and charges on the account: the group's choice**, a new
   required constitution setting `account_returns` (no WEPL default, as for
   the leaver rules):
   - `default_fund`: all of it to the default fund;
   - `by_fund_balance`: split across funds by what each holds at the account
     just before the line. If no fund holds anything, there is nothing to
     go by and the default fund takes it all.

   Inside each fund, `interest` and `bank_charges` then say who shares it,
   as before. One journal entry and one line resolution per fund.
   Constitutions adopted before this read as `default_fund`, which is what
   the software did while they were in force.
6. **Corrections stay in the fund the line went to.** An unattributed
   pay-in is credited to the member in the fund it arrived in. An
   unexplained outflow explained by another fund's mandate is booked as two
   entries: the default fund gets its cash back, the mandate's fund pays
   (`payout_explained_elsewhere`). The account's total does not move.
7. **Reconciliation is per account**, against the sum of its funds
   (`account_position`). Reports show the total, each fund, and each
   member's total across funds.

## Alternatives

- **One fund per group:** simplest, but drops the group's welfare and
  project pools the constitution template already has (§3).
- **A separate bank account per fund:** not available; Harry, 2026-10-04.
- **Bank virtual account numbers per fund:** the cleanest routing if the
  bank offers it. Added to the questions for the bank. If it exists, it
  replaces the code without changing the books.

## Consequences

- Members must be told each fund's code. A pay-in without one, or with a
  mistyped one, goes to the default fund. Moving money between funds is a
  group decision, built by ADR-0024. Re-routing a mistyped pay-in to its
  fund is a separate correction, ADR-0025.
- The default fund cannot close while the account is open (custody 0007
  trigger, unchanged). Any other fund closes once it holds nothing.
- Opening balances are brought in to the default fund.
- Every group's constitution must now state `account_returns`.
