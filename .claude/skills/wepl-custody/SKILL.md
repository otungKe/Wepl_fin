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
   - **deposit.** `domain/attribution.attribute` looks for a member code in the
     reference or narration, then a remembered payer (`PayerMapping`), then
     the member's own number. Otherwise the money goes to `unattributed_in`
     and a `correct_records` holder is asked once. A code quoted from a membership spell that ended is held, never moved to another spell (ADR-0012).
   - **interest / charge.** Shared pro rata by member balances, or retained,
     per the constitution (`ConstitutionRules.interest` / `bank_charges`).
   - **withdrawal.** `domain/matching.match_outflow`:
     - A quoted `WM…` reference must name an issued mandate in this fund for
       exactly this amount.
     - With no reference, it must be the *single* issued mandate with this
       amount, and this payee when the bank reports one.
     - The claim is `governance.public.execute_mandate`, a conditional UPDATE.
     - No match: `unexplained_out`, an `unmatched_outflow` alert, and an alert
       notification to **every** active member.
4. **reconcile.** It compares ledger `custody_cash` with the latest running
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
- **Opening balances come first.** They must be recorded before any other
  line, with sequence 0. Anything the signers cannot account for goes to
  `unattributed_in`, never to a member.
- **Group checks everywhere.** Every correction checks that the member or
  mandate belongs to the line's group and fund.

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
