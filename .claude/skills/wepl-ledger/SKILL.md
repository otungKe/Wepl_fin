---
name: wepl-ledger
description: The rules of Wepl_fin's double-entry ledger — post_journal() as the only
  money door, JournalDraft as the accounting decision, derived balances, journal
  immutability in the domain and in PostgreSQL, idempotency keys and fingerprints,
  reversals, and Money. Use whenever touching backend/contexts/ledger, any
  accounting decision (custody/domain/accounting.py), or anything that reads a balance.
---

# Wepl_fin ledger

`backend/contexts/ledger` is the **single source of monetary truth**. Breaking
what follows fails a domain check, a PostgreSQL trigger, or both. Background:
ADR-0003. Adapted from the original WEPL repo's `wepl-ledger` skill (PR #205);
the lessons carried over, the machinery here is different.

## The distinction that matters most

**Journal state ≠ workflow state.** They are different facts with different owners.

| | Journal (ledger) | Workflow state (other contexts) |
|---|---|---|
| Objects | `JournalEntry` + `JournalLine` | `Mandate.status`, `Proposal.status`, `LineResolution.outcome` |
| Question | What did the books record? | Where is this in its process? |
| Values | none: **posted, or not posted** | explicit state machines (`governance/domain/lifecycle.py`, `custody/domain/resolution.py`) |
| Mutability | **immutable** (domain + DB triggers) | moves only along declared transitions |
| Correction | a **new entry** (reversal or correcting entry) | a transition, or a new resolution row |

- A journal **has no state machine and must never get one.**
- A mandate being `executed` is not evidence that money moved. A balanced
  journal touching `custody_cash` is.
- Never mirror journal facts into a column; never store a balance.

## The single door

`contexts.ledger.public.post_journal(draft)` is the only way to create journal rows.

1. The owning context's **domain** makes the accounting decision and returns a
   `JournalDraft` (custody's is `custody/domain/accounting.py`). Build drafts
   with `JournalDraft.build(...)`, which merges and drops zeros.
2. Constructing a `JournalDraft` proves it is valid. It has ≥ 2 positive
   postings, stays in one group and fund, uses each account's currency and
   balances per currency.
3. `post_journal` resolves accounts (created on first use, race-safe), writes
   the entry and its lines atomically, and stamps the audit operation id.

This is enforced independently of the Python code:
- **`ledger/infrastructure/migrations/0002_database_rules.py`**:
  - A `DEFERRABLE INITIALLY DEFERRED` constraint trigger re-sums every entry
    at COMMIT and requires at least 2 lines.
  - BEFORE UPDATE/DELETE/TRUNCATE triggers on `ledger_account`,
    `ledger_journalentry` and `ledger_journalline` block raw SQL too.
- A CHECK constraint requires `amount > 0`.
- **`tests/test_architecture.py`**: no context may import ledger internals, and
  no mutable money counter (`<amount|balance|total…> = F(...)`) may appear.

## Accounts

Keyed by `AccountKey(group_id, fund_id, purpose, member_id?, external_account_id?, currency)`.

| Purpose | Normal side | Meaning |
|---|---|---|
| `custody_cash` | D | money at the custodian (needs `external_account_id`) |
| `member_interest` | C | one member's share (needs `member_id`) |
| `unattributed_in` | C | received, payer unknown |
| `unexplained_out` | D | paid out with no mandate: alerted |
| `retained` | C | group-level money |

**Invariant:** `cash = member interests + unattributed + retained − unexplained out`.
`FundPosition.invariant_holds` checks it. The ledger knows ids only; it
imports no other context.

## Idempotency

- **Replay returns the first entry.** Posting a key again returns that entry.
- **Reuse is refused.** Reusing a key for **different** content raises
  `LedgerError`; the comparison is `JournalDraft.fingerprint()`, which ignores
  posting order.
- **Custody key shapes.** Keys come from the statement line, e.g.
  `line:{id}:receipt`, `line:{id}:payout`, `line:{id}:attribute:{n}`,
  `line:{id}:explain:{n}`. Do not rename them casually: a replay after a
  crash relies on the same key.
- **Domain rows are not covered.** Idempotency outside the journal is not free.
  `post_journal`'s dedup does not cover a domain row written next to it:
  - Custody guards its `LineResolution` with `latest_outcome()` before deciding.
  - Corrections check `ensure_correction()` before posting.

  Any new service that writes both must guard the domain row *before* it moves.
- **Derive, never count.** The original WEPL lost money-count correctness
  three times with running counters. Derive from the journal
  (`member_balances`, `fund_position`, `member_movements`).

## Reversal

`reverse_journal(entry_id, idempotency_key=...)` posts the mirror image, links
`reverses`, is idempotent on its key, and refuses a second reversal under a
different key. Nothing is ever edited.

## Money

- `contexts.shared_kernel.money.Money` is a frozen `Decimal` plus currency, at
  **2 dp** (KES minor unit). It rejects floats, sub-cent input and NaN.
  Cross-currency arithmetic raises.
- `Money.allocate(weights)` is the **only** rounding point: largest remainder,
  deterministic ties, parts always sum to the whole. Do not write a second
  implementation.
- **Never `float`.** Pass strings or `Decimal`.

## Forbidden shortcuts

- Creating `JournalEntry`/`JournalLine` anywhere but
  `ledger/application/posting.py`, including in migrations and commands.
- Editing or deleting a posted entry, disabling a trigger, or
  `SET session_replication_role = replica`.
- Storing a balance "for performance". Derive it.
- A state machine on journals.
- Mocking `post_journal` in a test; it is the thing under test.
- A network call inside a transaction that posts.

## Key tests

- `contexts/ledger/tests/unit/test_journal.py` (domain rules)
- `contexts/ledger/tests/integration/test_posting.py` (idempotency,
  fingerprint, reversal, and the DB rules exercised by bypassing the domain)
- `tests/test_properties.py` (books = bank over random histories)

## Contributions and arrears (ADR-0022)

- Each fund's contribution rule is in the group's constitution; every
  setting is the group's choice, with no WEPL default. Never add a default:
  add a group choice instead.
- `contexts/contributions` derives what is due, arrears, paid-ahead amounts
  and late fines from the rule and the member's pay-ins. It stores no
  counter and posts no entry. A fine is owed until paid and moves no money
  (Harry, 2026-10-05). It is paid into the fund the rule names (`pay_into`):
  custody books such a pay-in as `fine_payment` to that fund's `retained`,
  never to the member's share.
