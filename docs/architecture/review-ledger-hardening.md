# Review: ledger hardening (2026-10-06)

- **Requested by:** Harry, "hardening review, not a redesign" of `contexts/ledger`.
- **Baseline:** `main` at `e0f221c` (PR #15 and #16 merged). The accepted
  baseline is `review-ledger-production.md` (2026-10-01); its completed
  hardening is not reopened.
- **Scope:** every file in `backend/contexts/ledger` (domain, application,
  infrastructure, migrations 0001–0009, `contract.py`, `public.py`, tests),
  the triggers other contexts put on ledger tables (communities 0013,
  custody 0005/0008), the ledger's callers in custody and governance, and
  the cross-context ledger tests in `backend/tests/`.
- **Method:** read the code and the SQL, then probed each doubtful rule on
  PostgreSQL 16 as `wepl_app` (the role row-level security binds), on real
  connections that commit where concurrency mattered.
- **Labels:** CONFIRMED means probed or tested; INFERRED means read from the
  code, not run.

## 1. Verdict

**Accept the ledger as WEPL's foundation, with the fixes in this change.**

What holds, CONFIRMED by the existing tests and this pass's probes:
- every entry balances per currency, with at least two positive lines, in
  one group, fund and tenant;
- history is append-only, and an entry is sealed when its transaction ends;
- a reversal mirrors its original exactly and happens at most once; a
  reversal can itself be reversed;
- idempotency is per tenant, and the fingerprint covers the money;
- a fund transfer keeps ownership and commits as both legs or neither.

PostgreSQL enforces each of these, not only the Python.

This pass found:
- **no Critical issue.** Nothing lets a current code path post wrong money
  or cross a tenant.
- **two High issues.**
  - One is a database rule that was not safe under concurrency: fund-transfer
    pairing. It is now fixed.
  - The other is architectural: the application role owns the tables it
    writes. So PostgreSQL stops honest code, but not arbitrary SQL. That needs
    an ADR, so it is not fixed here.
- **some Medium and Low issues.** They are about reporting and monitoring,
  not about the money. They are fixed, except one DB rule that belongs to
  communities.

## 2. Findings, by severity

### Critical

None.

### High

**H1. The application role owns the ledger's tables, so PostgreSQL binds
honest code but not arbitrary SQL from that role.** *Architectural
weakness; not fixed here; needs an ADR.*

- **Why it matters.** "PostgreSQL is the final enforcement boundary" holds
  against application bugs that use ordinary writes. It does not hold
  against anyone who can run SQL as `wepl_app`, for example through an
  injection or a compromised host. Such a person can rewrite posted history.
- **The rule involved.** Migrations run as `wepl_app`, which owns every table
  (`ci.yml`: `ALTER DATABASE wepl OWNER TO wepl_app`). An owner can disable
  user triggers, drop policies and turn off `FORCE ROW LEVEL SECURITY`.
  CONFIRMED as `wepl_app`:
  - `ALTER TABLE ledger_journalline DISABLE TRIGGER ledger_journalline_append_only_row`,
    then `UPDATE` of a posted line's amount, succeeded;
  - the commit-time balance triggers can be disabled the same way. The new
    bypass tests use exactly this.
- **The seal can be forged.** 0005 seals an entry with a transaction-local
  setting, `wepl.ledger_open_entries`. Any session can set it:
  `set_config('wepl.ledger_open_entries', ',<id>,', true)`. After that, a
  balanced pair of new lines was accepted on an entry committed earlier.
  CONFIRMED. This is the same class of problem, not a separate one: an
  owner can drop the trigger anyway.
- **Smallest justified fix.** Split the roles:
  - a schema-owner role runs migrations and owns the tables;
  - `wepl_app`, the runtime role, is granted only `SELECT, INSERT` on the
    journal tables and `USAGE` on their sequences: no `UPDATE`, `DELETE`,
    `TRUNCATE` or ownership.

  Append-only then also holds by privilege, and triggers and policies are out
  of the runtime role's reach. This touches every context, settings, CI, the
  restore drill and deployment, so it needs an ADR first.
- **Afterwards, optionally:** replace the setting-based seal with a check on
  the entry row's inserting transaction (`xmin` still in progress means it is
  this transaction's). That only matters once the runtime role can no longer
  drop the trigger.

**H2. Fund-transfer pairing (ledger 0009) was not concurrency-safe.**
*Real database defect; fixed.*

- **Why it matters.** 0009 promises exactly one leg out and one leg in per
  transfer. It checked that at commit, by counting legs with the same cause.
  A commit-time check cannot see another transaction's uncommitted rows.
  So two transactions posting the same transfer under different idempotency
  keys each saw only their own pair, and both committed.
- **Evidence.** CONFIRMED on two real connections:
  - four legs were committed;
  - the member's interest in the source fund went to −60;
  - only the nightly check noticed.
- **Reachability.** No current caller reaches this. Custody derives the keys
  from the transfer id (`fund_transfer:{id}:out`/`:in`) and holds the
  custodian-account lock. But the database rule claimed a guarantee it did
  not give.
- **Fix: ledger 0010, `ledger_transfer_leg_once`.** A partial unique index on
  `(tenant, cause_type, cause_id, kind)` for the two transfer kinds. The
  second writer now waits on the first writer's leg, then fails.
  `post_transfer` reports that as `LedgerError("… already been posted under
  another key")`. A retry under the same keys still replays.

### Medium

**M1. A retry that raced its own reversal was told "already reversed".**
*Real defect (idempotency contract); fixed.*

- **Evidence.** CONFIRMED: eight concurrent `reverse_journal(e,
  idempotency_key="same")`. Two got the reversal's id; six got
  `LedgerError("already been reversed")`.
- **Cause.** The reversal insert collides on two unique indexes: the
  `reverses_id` key (from 0001, checked first) and the idempotency key.
  `_post` mapped the first one to "already reversed" without asking whether
  the winner used the same key.
- **Effect.** The money was safe (one reversal), but an honest retry was
  reported as a failure.
- **Fix: `posting.py`.** On any of the three unique races, look the key up
  first and replay it if it exists. Only then translate the race into "already
  reversed" or "transfer already posted".

**M2. The ledger accepts accounts in a currency the fund does not hold, and
two queries added amounts across currencies.** *Real defect in queries
(fixed). Missing database rule (owned by communities; not done here).*

- **What is right.** Balance per currency is correct in the domain and in
  PostgreSQL: the 0002 trigger groups by `a.currency`.
- **The gap.** Nothing ties an account's currency to its fund's currency.
  CONFIRMED: a USD entry posted into a KES fund (communities 0011 makes
  funds KES-only) was accepted.
- **Two queries mixed currencies.**
  - `trial_balance(fund)` summed every currency, and `check_books` used it.
    The KES check therefore recorded a cross-currency number, and a KES
    surplus could hide a USD shortfall.
  - `member_movements` ran one balance across currencies.
- **Fix.**
  - Both queries now take `currency`, defaulting to KES like the other
    queries.
  - The check records each currency's own trial balance.
- **Still needed: a database rule.** An account's currency must equal its
  fund's currency. That rule belongs in communities'
  `communities_ledger_names_its_own_fund` trigger, which already checks
  ledger rows against `communities_fund`. The Communities thread is changing
  that trigger now (posting into a closed fund), so add the rule after that
  change lands.

**M3. The integrity check was not independent of what it checks.** *Real
monitoring defect; fixed.*

The check only looked at fund totals, and read them through the product's
own query. CONFIRMED by tests that fail on the old code:
- **Offsetting entries passed.** Two unbalanced entries that offset each
  other (D10/C9 and D9/C10, written with the balance triggers off) passed:
  the fund still netted to zero.
- **Positions came from the product query.** The check read positions
  through `fund_position`, so a wrong but self-consistent result would pass.
  The invariant `cash = interests + unattributed + retained − unexplained` is
  algebraically the trial balance. It catches a sign bug only if the totals
  are computed independently.
- **Cross-currency trial balance** (M2).

The fix is `infrastructure/books.py`, plain SQL that shares nothing with
`queries.py`. From it, the check computes:
- **per entry:** at least two lines, every line in the entry's fund, and
  balanced in each currency (`broken_entries`);
- **per purpose:** its own debit and credit totals, signed by
  `AccountPurpose.normal_side`;
- **agreement:** whether `fund_position` and `trial_balance` agree with those
  totals (`queries_agree`).

`passed` requires every check, and a CHECK constraint
(`ledger_check_passed_means_every_check`) stops a row claiming otherwise.

The check is still monitoring, never truth:
- it writes only `ledger_integritycheck`;
- the only reader is the operator inbox (`latest_checks`, the `passed` flag);
- nothing reads its amounts as balances.

**M4. The nightly command stopped at the first tenant that raised.**
*Real operational defect; fixed.* An exception in one tenant aborted the
command, so every later tenant went unchecked that night. Now each tenant
is checked on its own: the command writes `COULD NOT CHECK tenant N` to
stderr, continues, and exits non-zero. The nightly digest picks that up.

### Low

**L1. `_unpaired_transfers` ran one query per transfer leg.** It also missed
a second leg of the same kind when seen from that leg's own fund. *Fixed:*
one query per fund in `books.py`, using the cause index. A leg is paired
when its cause has exactly two legs and the other kind is in another fund.

**L2. PostgreSQL did not hold a reversal to the domain's identity rule.**
The domain requires a reversal's cause to be `journal_entry:<reversed id>`,
which puts the reversed entry in the fingerprint. The database did not
require it, nor that a transfer leg reverses nothing. *Fixed:* CHECK
`ledger_reversal_names_its_original`.

**L3. An empty kind or cause was accepted.** A `cause_id` of `None` was
stored as the text "None". *Fixed:* the domain refuses it, plus CHECK
`ledger_entry_has_kind_and_cause`.

**L4. `entry_fund` raised `JournalEntry.DoesNotExist`.** That is an internal
type, and under RLS it also stands for "another tenant's". *Fixed:* it now
raises `LedgerError("Unknown journal entry …")`, like `load_draft`.

**L5. The fingerprint text includes Python's enum and dataclass repr.** This
was known risk 3 of 2026-10-01. A Python upgrade that changed it would
refuse every honest replay of an older entry; the failure is safe, but
disruptive. *Not changed* (that would need a migration of stored
fingerprints). *Added* a test that pins the exact text, so CI fails before
production does.

**L6. The seal setting grows with each entry posted in a transaction.** This
was known risk 2 of 2026-10-01. Today's writers post a few entries per
transaction. Left as is.

### Future considerations (no change now)

**F1. Negative member-interest and retained balances are possible, and
partly legitimate.** The ledger has no non-negativity rule, and should not
get one:
- **Bank-observed outflows must be recorded as they happened**, even when
  they exceed what the books hold. Examples: an authorised payout the bank
  executed; a bank charge booked to `retained` (custody
  `accounting.charge`). Refusing them would make the books disagree with the
  bank.
- **A balance CHECK or trigger is itself a write-skew.** Two concurrent
  debits each see the old balance, so it would not hold under concurrency
  without a lock anyway.

For moves WEPL initiates (fund transfers; the ADR-0025 pay-in move), the
safe pattern is already in place:
- custody takes the custodian-account row lock
  (`ExternalAccount … select_for_update()`), the same lock ingestion and
  corrections take;
- it re-reads the balances under that lock;
- it posts in the same transaction.

Keep that pattern for every new decision that takes money from an owner.

If Harry wants it, the nightly check could later *report*, not fail, a
member or retained account below zero, as an operator item.

**F2. Scale.** Every balance is a sum over lines, and the check's per-entry
pass reads each line of the fund once, like `fund_position`.

ADR-0016's threshold, 100,000 lines in one fund (watched nightly), still
governs. If it is reached, the projection to build is a checkpoint row per
account at a given entry id. It would be:
- derived from the journal, append-only and rebuildable;
- verified nightly against the lines;
- never authoritative.

No stored balance before that.

**F3. Order.** `member_movements` orders by entry id, which is insertion
order, not commit order (accepted on 2026-10-01). No balance depends on ids;
only that display order does. `created_at` is set by the application when
the entry is inserted.

**F4. Dates.** `created_at` is the booking time. The bank's value date lives
on custody's statement line, which is the entry's cause. Nothing today needs
an effective or value date in the ledger. Period-end statements by value
date, or interest accrual, would. Do not add one before then.

**F5. Account taxonomy.** The five purposes cover today's scope:

| Purpose | What it covers |
|---|---|
| `member_interest` | contributions |
| `retained` | fines (into a group fund), and charges or interest the group keeps |
| `member_interest` (pro rata) | charges or interest shared among members |
| `unattributed_in` | money received whose payer is unknown |
| `unexplained_out` | money that left without a mandate |

The core does not depend on purposes: entries, lines, balancing, reversal,
idempotency and transfers would all work unchanged. Fees, income, expenses,
liabilities, receivables or settlement accounts would each be:
- a new `AccountPurpose`;
- a migration updating `ledger_account_purpose_known` and
  `ledger_account_normal_side_follows_purpose`;
- an extension of `FundPosition` and of the check's sums.

A missing extension fails the check loudly; it does not hide money. WEPL's
own income (fees) would need its own books, separate from any group's fund.
That is a decision for when fees exist.

## 3. Answers to the twelve questions, briefly

1. **Double-entry.** No path creates an unbalanced entry. The domain refuses
   one, and the deferred trigger re-sums every entry per currency at commit
   (0002 and 0005). Domain and database now agree, including on reversal
   identity (L2) and kind and cause (L3). Gap: an account's currency is not
   tied to its fund's (M2).
2. **Append-only.** UPDATE, DELETE and TRUNCATE are refused on accounts,
   entries and lines, and posted entries are sealed. This is sufficient
   against application code; not against the owner role (H1).
3. **Isolation.** Each link is checked independently of row-level security:
   - lines, entries, accounts and reversals by composite (id, tenant) keys
     (0008);
   - lines against their entry's group and fund by a trigger (0005);
   - fund, group and member by communities 0013;
   - the cash account's custodian account by custody 0005/0008.

   A reversal stays in its tenant, and in its fund because it mirrors the
   original's accounts. CONFIRMED by the existing `test_database_rules`,
   `test_linked_rows` and `test_isolation`.
4. **Idempotency.**
   - **Scope:** the key is unique per tenant, and the fingerprint covers
     kind, cause and every posting.
   - **Concurrent identical requests** post once (existing race tests).
   - **A reused key with different content** is refused.
   - **Duplicate financial effect:** possible only through a transfer
     reposted under new keys (H2, fixed).
   - **Same-key reversal retries:** misreported (M1, fixed).
5. **Reversals.** At most once, by unique key. A reversal of a reversal is
   allowed. Concurrent reversals under different keys post exactly one
   (existing test). Bypass via raw SQL is refused: mirror at commit, tenant,
   and now cause (L2).
6. **Transfers.**
   - **Ownership:** kept; the legs mirror, in the domain and at commit.
   - **Atomicity:** both legs are in one transaction, and the pair is checked
     at commit.
   - **One leg alone:** refused.
   - **Concurrency:** was broken under different keys (H2, fixed); retries
     replay (new test).
   - **Negative balances:** possible from bank events; prevented for
     transfers by custody's lock (F1).
7. **Account model.** Sufficient (F5).
8. **Queries.**
   - **Currency:** two queries mixed currencies (M2, fixed).
   - **Order:** no reliance on ids except display order (F3).
   - **N+1:** one, in the check (L1, fixed).
   - **Full scans:** per fund, bounded by ADR-0016.
9. **Integrity monitoring.** It was not independent (M3), the command was
   fragile (M4), and transfer pairing was N+1 (L1). All are fixed, and the
   check stays monitoring only.
10. **Causation.**
    - `cause_type`/`cause_id` trace an entry to its business operation
      without the ledger importing anyone, and are now non-empty (L3).
    - `operation_id` ties an entry to the audit trail.
    - `reverses` links corrections; transfers pair by cause.
    - No new dates (F4).
11. **Tests.** See section 6.
12. **Public contract.** See section 4.

## 4. Things that should NOT be changed

- **The single door.** `post_journal` / `post_transfer` stay the only way
  to write money; `JournalDraft` remains the accounting decision.
- **No stored balances or balance cache.** No checkpoints below ADR-0016's
  threshold.
- **Reversal rules.** Reversal of a reversal stays allowed, and each entry
  is reversed at most once (ADR-0003).
- **Transfers.** Two single-fund entries, never reversed (ADR-0024).
- **The memo stays outside the fingerprint.**
- **No non-negativity rule in the ledger** (F1).
- **No new account purposes, no value or effective dates** (F4, F5).
- **The public surface.**
  - `contract.py` is pure types.
  - `public.py` exposes posting, reversal and read queries.
  - `load_draft`, `accounts.resolve` and the models stay internal; only
    tests import them.
  - `entry_credits` and `entry_fund(s)` are narrow read helpers custody
    needs. Keep them read-only.

  No change.
- **The integrity check stays monitoring.** It never corrects, and it is
  never read as a balance.

## 5. Hardening plan, in order

1. **This change** (ledger 0010 plus code): H2, M1, M2 (queries), M3, M4,
   L1–L5.
2. **H1, role separation.** An ADR, then a separate schema-owner role for
   migrations, and a runtime role with `SELECT, INSERT` only on the journal
   tables. Add a test that the runtime role cannot `ALTER`, `UPDATE` or
   `DISABLE TRIGGER`. Do this before production and the bank's due
   diligence; it does not block the next context.
3. **M2, database rule,** after the Communities change lands: an account's
   currency equals its fund's, in `communities_ledger_names_its_own_fund`.
4. **After step 2, optionally:** replace the setting-based seal with an
   `xmin`-based one (H1).
5. **Only if Harry wants it:** a nightly warning, not a failure, for
   negative member or retained balances (F1).

**Related, owned by the Communities thread.** A fund can close while a
concurrent pay-in posts into it. That thread is adding a database check that
the fund is open. It has the same shape as H2: a check that reads the fund's
status without a lock lets the close and the posting each miss the other.
The trigger should lock the fund row (`FOR KEY SHARE` or `FOR SHARE`) so a
concurrent close waits. Alternatively, closing should take the lock the
posting path takes.

## 6. Tests

### Added in this change

Each test fails on the old code (run with the old source and the new
tests: 14 failures, 11 errors).

| Test | Proves |
|---|---|
| `tests/test_ledger_concurrency.py::TransferRaceTests::test_one_transfer_under_two_keys_at_once_is_posted_once` | H2 on real connections: exactly one pair; the other caller gets a clear error |
| `…::test_racing_retries_of_one_transfer_all_get_its_entries` | eight identical transfer retries replay to one pair |
| `…::LedgerRaceTests::test_racing_retries_of_one_reversal_all_get_its_id` | M1: eight identical reversal retries all get the same id |
| `test_transfers::test_a_transfer_already_posted_under_other_keys_is_refused` | H2 in one transaction |
| `test_database_rules::EntryIdentityRuleTests` (3) | L2, L3 in PostgreSQL, bypassing the domain |
| `test_integrity::BypassedRulesTests` (3) | M3: offsetting unbalanced entries, an entry with no lines, and a cross-currency imbalance all fail the check, with the balance triggers off |
| `test_integrity::…::test_a_balance_query_that_is_wrong_but_consistent_fails_the_check` | M3: a query bug fails the check |
| `test_integrity::NightlyCommandTests` | M4 |
| `test_posting::…stay_in_one_currency` | M2 queries |
| `test_posting::test_reversing_an_unknown_entry_is_a_ledger_error` (extended) | L4 |
| `unit/test_journal` (2) | L3 in the domain; L5 fingerprint pinned |

Two existing tests changed. `test_a_failure_is_recorded_audited_and_alerted_once`
now breaks the check's own sums rather than the product query. The raw
reversals in `test_database_rules` now name their original, so they reach
the deeper rule they test.

### Still worth adding (not done)

- **H1:** a test that the runtime role cannot alter or update ledger tables,
  once the roles are split.
- **A property test:** random histories of postings, reversals and transfers
  keep `check_books` passing, in `tests/test_properties.py`.
- **A custody race:** a transfer racing a payout on the same fund through
  custody, proving its account lock. Custody's suite owns this.

## 7. Evidence

- **Database and role:** PostgreSQL 16, as `wepl_app` (not a superuser, no
  BYPASSRLS).
- **Full suite:** 440 tests, OK, with `WEPL_PROPERTY_EXAMPLES=150`. The suite
  had 425 tests before this change; it adds 15 tests and extends one
  existing test.
- **`makemigrations --check`:** clean.
- **Migration and demo:** `migrate` from empty, then `demo_custody_pilot`;
  the neighbour sees 0 rows.
- **Nightly command:** `check_ledger_integrity` reports 1 fund book checked,
  0 failed and 0 tenants not checked.
- **Restore drill:**
  - Parts 1–2 passed: every row and every guard is identical (44 functions,
    24 policies, 39 tables with RLS, 39 tables, 85 triggers, including the
    new constraint and index).
  - Part 3 (the application on the copy) could not run locally, because of
    how this container installs Python packages. CI runs it.
- **0010 is safe under row-level security.** CONFIRMED on a scratch table
  with forced RLS and no tenant context, where 0 rows are visible: `CREATE
  UNIQUE INDEX` still found the duplicate rows, and `ADD CONSTRAINT … CHECK`
  still found the violating row. 0010's index and checks therefore cover
  every tenant's existing rows, unlike a foreign key's validation.

## 8. Final recommendation

**After this change merges, the ledger is ready for the next WEPL context.**

Do H1 (role separation) before production and the bank's due diligence. It
is the one place where "PostgreSQL is the final boundary" is not yet true,
and it is an ADR-sized change across every context, not a ledger patch.
