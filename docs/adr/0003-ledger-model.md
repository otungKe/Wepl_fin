# ADR-0003: Double-entry, append-only ledger

- **Status:** Accepted (Harry, 2026-10-03), after every item of his acceptance
  checklist passed; evidence in `docs/architecture/adr-0003-acceptance.md`.

## Decision

Accounts are keyed by fund, purpose, member (member interests only), external
account (custody cash only) and currency. They are created on first use.

| Purpose | Normal side | Meaning |
|---|---|---|
| `custody_cash` | debit | Money at the custodian for this fund |
| `member_interest` | credit | What the group owes one member |
| `unattributed_in` | credit | Received, payer not yet known |
| `unexplained_out` | debit | Paid out with no mandate: alerted |
| `retained` | credit | Group-level money no single member owns |

**Invariant.** `cash = member interests + unattributed + retained − unexplained out`.

Money moves as: business event → accounting decision (the owning context's
domain builds a `JournalDraft`) → `ledger.post_journal`.

Integrity is enforced at several layers (rule 47):

- **Domain.** A `JournalDraft` cannot be built unless it has at least two
  positive postings, stays within one group and fund, and balances per
  currency.
- **Application.** Posting is idempotent by key. Reusing a key for different
  content is refused (content is compared by fingerprint).
- **PostgreSQL.** A deferred constraint trigger re-checks balance and the
  two-line minimum at commit. A CHECK constraint requires amounts > 0.
  Triggers reject UPDATE, DELETE and TRUNCATE on accounts, entries and lines.

Corrections are reversals or new entries, never edits (rule 19). Balances are
always derived from the journal, never stored (rules 18, 27).

**Reversals (Harry, 2026-10-01).**
- A reversal is an ordinary, immutable journal entry that mirrors another.
- Every entry, a reversal included, can be reversed **at most once**. So a
  reversal that was itself posted wrongly is corrected by reversing it:
  `original → reversal → reversal of the reversal`. Each step is a new
  entry, with no edit and no special case.
- There is deliberately **no rule against reversing a reversal**.
- Enforcement:
  - "at most once" is a unique constraint on `reverses`;
  - "mirrors exactly" and "same tenant" are triggers (ledger 0005);
  - a reversal's cause is the entry it reverses, which puts that entry in
    its idempotency identity.
- Pinned by `test_a_reversal_is_itself_reversible_once`.

## Consequences

- No code path, shell session or future context can commit an unbalanced or
  edited ledger.
- Test data cannot be truncated, so tests use transaction rollback
  (`TestCase`), not table flushes.
