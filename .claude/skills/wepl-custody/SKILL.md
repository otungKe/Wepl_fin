---
name: wepl-custody
description: How Wepl_fin watches money it does not hold — custodian accounts,
  statement ingestion (duplicates, conflicts, gaps), attribution of pay-ins,
  mandate matching for payouts, unmatched-outflow alerts, corrections, opening
  balances and reconciliation, plus the bank simulator and demo. Use when touching
  backend/contexts/custody, a connector, the simulator, or the custody demo.
---

# Wepl_fin custody

In the pilot, groups keep their money in their own Chama Accounts at the custodian bank, and WEPL
never holds or moves it (ADR-0006, custody Model A). The design is in
`/mnt/project-files/wepl-custody/wepl-custody-design-im.md`, which includes
the questions still open with the bank.

## The pipeline

`custody.public.sync(ea_id, connector)` runs these steps:

1. **fetch.** `connector.fetch(account_number)` returns `BankLine`s. It runs
   outside any transaction.
2. **ingest.** Lines are taken in custodian `sequence` order, one transaction
   per line, with `ExternalAccount` locked. For each line:
   - Same `external_id`, same kind, amount and sequence: counted as a
     duplicate and ignored.
   - Same `external_id` with different details: a `statement_conflict` alert.
     The line is **not** posted; the first version stands.
   - Otherwise it is stored as an immutable `StatementLine`, then `account_for`
     decides and posts.
3. **account_for.** It is skipped if the line already has a resolution. It
   then dispatches by kind:
   - **which fund.** One account holds all the group's funds (ADR-0023).
     A deposit goes to the fund whose code is in the reference
     (`domain/routing.fund_for`), else the default fund
     (`ExternalAccount.fund`). A withdrawal goes to its mandate's fund;
     an unmatched one to the default fund.
   - **deposit.** `domain/attribution.attribute` looks for a member code in the
     reference or narration, then a remembered payer (`PayerMapping`), then
     the member's own number. Otherwise the money goes to `unattributed_in`
     and a `correct_records` holder is asked once. A code quoted from a membership spell that ended is held, never moved to another spell (ADR-0012).
   - **interest / charge.** Split across funds as the group chose
     (`account_returns`: `default_fund` or `by_fund_balance`), one entry per
     fund; inside each fund shared pro rata by member balances, or retained
     (`ConstitutionRules.interest` / `bank_charges`).
   - **withdrawal.** `domain/matching.match_outflow`:
     - A quoted `WM…` reference must name an issued mandate of this group for
       exactly this amount.
     - With no reference, it must be the *single* issued mandate with this
       amount, and this payee when the bank reports one.
     - The claim is `governance.public.execute_mandate`, a conditional UPDATE.
     - No match: `unexplained_out`, an `unmatched_outflow` alert, and an alert
       notification to **every** active member.
4. **reconcile.** It compares ledger `custody_cash`, summed over every fund
   held at the account (`account_position`), with the latest running
   balance, finds sequence gaps and unresolved lines, and records a
   `ReconciliationRun`. It also walks the running balance line by line
   (`balance_breaks`): each printed balance must equal the one before plus or
   minus the line. That finds a missing line where the numbering cannot,
   because the custodian's printed statements carry no transaction id or
   sequence (samples of 2026-10-03), and a feed's numbering may be derived.
   Anything off raises a `recon_difference` alert.

"Balanced" means the books equal the bank. An unmatched outflow still
reconciles; the alert is the control, not the reconciliation.

## Rules to preserve

- **Ambiguity is never a match.** A wrong match hides an alert, which is worse
  than a false alarm.
- **Statement lines are facts.** They are append-only and never edited;
  provider detail goes in `metadata`.
- **Corrections are new rows.** They follow `domain/resolution.CORRECTIONS`:
  `unattributed → attributed` via `attribute_payment`, and `unmatched →
  explained` via `explain_outflow`. Each is a new journal entry plus a new
  `LineResolution`.
- **A pay-in in the wrong fund is moved, not transferred** (ADR-0025):
  `move_pay_in(line, fund, by, reason)` posts two entries (out of the wrong
  fund, into the right one, same owner) and two resolutions (`moved`, then
  the line's outcome again). PostgreSQL refuses a `moved` with no booking
  after it (custody 0009). Arrears count a line by its latest resolution
  only (`member_pay_ins`).
- **Opening balances come first.** They must be recorded before any other
  line, with sequence 0. Anything the signers cannot account for goes to
  `unattributed_in`, never to a member.
- **Group checks everywhere.** Every correction checks that the member or
  mandate belongs to the line's group. A correction posts in the fund the
  line went to (`bookkeeping.line_fund`); a mandate of another fund moves
  the outflow there in two entries (ADR-0023).

## The simulator and the demo

- **`backend/simulators/custodian_bank/bank.py`:**
  - `open_account`, `deposit` (paybill 542542 style), `withdraw`,
    `credit_interest`, `charge`, `balance`.
  - The bank refuses overdrafts.
- **`connector.py::SimulatorConnector(Faults(duplicate_rate, withhold_rate,
  reorder, seed))`:** a faulty push feed. `sweep=True` is the complete,
  ordered end-of-day statement.
- **`python manage.py demo_custody_pilot`:** the 20-minute custody demo. It uses public
  surfaces only; keep it that way, because it is also CI's end-to-end check.

## Closing an account (ADR-0015 addendum)

- `close_external_account(ea, by, confirmed_by)`: two `correct_records`
  holders; refuses unless a fresh reconciliation shows a zero statement
  balance, no difference, gap, break or unaccounted line, and no open alert
  on its lines. Sync the final statement first.
- A closed account never reopens, never changes and takes no new line
  (custody 0007). Ingest refuses new activity on it, so `sync_accounts`
  fails loudly; collections calls are refused.
- The fund's close trigger counts only accounts that are still open.

## Moving money between funds (ADR-0024)

- Governance decides it (`propose_fund_transfer`, like a payout); custody
  books it with `book_fund_transfer`, under the lock of the group's open
  account, and the nightly `book_fund_transfers` books any approval still
  waiting.
- `accounting.fund_transfer` builds the pair: the source fund's owners give
  and its cash at the account goes down; the destination's cash at the same
  account goes up and the same owners receive the same amounts.
- Pro-rata takes the members who would share a pro-rata payout
  (`sharing_facts`, `Event.PAYOUT`), by their balances when booked.
- If the money is no longer there (`governance.contract.shortfall`, counting
  issued mandates and other approved transfers), the transfer fails and
  nothing posts. A transfer is not a pay-in: arrears never see it.

## Sharing and leavers (ADR-0014)

- `domain/sharing.py` decides who shares an event, judged on the line's
  `posted_at`: members in the group that day; leavers only as the group's
  own constitution choices say (`leaver_balances`, `leaver_rule_version`,
  `leaver_payouts`; no defaults). Never invent a leaver rule: add a group
  choice instead.

## Do not assume

- **Custodian formats are unknown.** The real custodian statement format, push
  notifications and APIs are UNKNOWN until Harry obtains a sample export and
  answers from the bank. The simulator's field names are placeholders.
- **Nothing has seen real money.** No invariant here has been exercised
  against a real bank. "Correct" means "correct under test and simulation".
- **Payouts are not WEPL's.** There is no payout submission (Model C); that
  would be a new `payments` context behind a provider port.
- **SMS is on hold.** Notifications log until Harry picks a provider.

## Key tests

- `contexts/custody/tests/unit/test_domain.py`
- `contexts/custody/tests/integration/test_ingestion.py`
- `contexts/custody/tests/integration/test_faults.py`
- `tests/test_isolation.py`
- `tests/test_properties.py`

## The bank's collections service on a group's account (ADR-0019, Accepted)

- A group's account linked with connector `business_connect` can take the
  bank's calls (`contexts/custody/api/`, `application/collections.py`).
- **`POST /collections/validate`** accepts a reference only if it is the
  mobile number or member code of a current member of the group whose
  account is named.
- **`POST /collections/notify`** sends the payment to that group's
  ordinary `ingest`.
- Finding the account from its number is the only cross-tenant step.
- Every request is signed (HMAC over `timestamp.body`, 5-minute window).
  The endpoints are off until `WEPL_COLLECTIONS_SECRET` is set.
- The payload is a placeholder until the bank's format is agreed.
- Attribution order: member code → a mobile number quoted as the reference
  (`attribution.quoted_msisdn`) → a remembered payer → the payer's own
  number. A quoted number that is not a current member's is held.

## The pooled collection account (withdrawn)

One WEPL collection account for every group was designed and built (ADR-0018),
then withdrawn on 2026-10-04: each group keeps its own account (ADR-0006).
The code is kept as a fallback in commit `79cb91f`. Don't rebuild or restore
it without Harry's word.
