# Review: the ledger as a financial core

- **Date:** 2026-10-01.
- **Requested by:** Harry, "You are reviewing the WEPL Ledger bounded context
  as a financial-core component".
- **Scope:** `backend/contexts/ledger/` (domain, application, infrastructure,
  migrations 0001–0005, contract, public), `shared_kernel/money.py`, the only
  writer (custody `bookkeeping.post_and_resolve`), and the ledger tests.
- **Baseline:** commit `0c0c050` (infrastructure hardening, see
  `review-ledger-infrastructure.md`). 230 tests.
- **Evidence:** code, migrations, and tests run against PostgreSQL 16 as
  `wepl_app`, the role row-level security binds. Each claim is classed
  CONFIRMED (tested or probed), INFERRED, or ASSUMPTION.

## Invariants the ledger must keep

1. Every entry has at least two lines, all positive, and balances per currency.
2. Every line of an entry is in the entry's group and fund, and its tenant.
3. Posted history is append-only. A correction is a new, mirror-image
   reversal, and an entry is reversed at most once.
4. One idempotency key per tenant means one entry. A replay returns it, and
   a different entry under the same key is refused.
5. One account per (fund, purpose, member, external account, currency).
6. Balances are derived from lines, never stored.
7. No tenant can read, post against, or reverse another tenant's rows.

## 1. Overall assessment

**Sound, and close to production-grade for the pilot's scope.** Every
invariant above is held by PostgreSQL, not only by the Python:
- constraints and triggers from 0001–0005;
- deferred balance checks;
- row-level security with FORCE.

The application layer adds clear errors and replay. This pass found no
CRITICAL defect, meaning nothing that could post wrong money or cross a
tenant. It found three IMPORTANT ones, all in how posting *reports*
failures and how it rebuilds a posted entry. All three are now fixed. The
architecture stays as it was.

## 2. Critical findings

None. CONFIRMED by the tests in section 7 and those from the infrastructure
pass:
- tenant isolation (A);
- concurrent reversal (E);
- account creation (G);
- database enforcement (H).

All of them hold under real, committed, concurrent transactions.

## 3. Important findings (all fixed)

| # | Finding | Class | Fix |
|---|---|---|---|
| B | `post_journal` read **any** `IntegrityError` as a race. If the key was not found and the target already had a reversal, it reported "already reversed", even when the failure was something else (a trigger, a check). In the replay branch, a missing key re-raised, which was correct, but nothing tied the replay branch to the key constraint. | CONFIRMED (test fails on the old code) | Classify by the violated constraint. `ledger_entry_key_unique` means replay; `ledger_journalentry_reverses_id_key` means "already reversed"; anything else re-raises unchanged. |
| C | A reversal's target was in its fingerprint only by convention: `JournalDraft.reversal()` sets the cause to the target. A hand-built draft could name one entry in `reverses_entry_id` and another, or none, in its cause. A key reused for a different target would then replay as "the same entry". | CONFIRMED by reading; no caller does this today | The domain now refuses a draft whose `reverses_entry_id` is set unless its cause is `journal_entry` / that id. Stored fingerprints are unchanged, so no migration is needed. |
| D | `load_draft` lost data and leaked an internal exception. | CONFIRMED (tests fail on the old code) | Pass `reverses_entry_id=entry.reverses_id`, order lines by `id`, and raise `LedgerError("Unknown journal entry …")`. |

Detail on D. The old `load_draft`:
- dropped `reverses_entry_id`, so a reloaded reversal looked like an
  ordinary entry;
- read lines in no defined order;
- raised `JournalEntry.DoesNotExist` for an unknown or foreign id. Under
  RLS a foreign id is indistinguishable from an unknown one, so the ledger
  error is the right one.

## 4. Improvements made

- The fingerprint's contract is written down in its docstring:
  - **covered:** kind, cause, and every posting (account, so group and fund,
    side, amount, currency);
  - **not covered:** the memo, which is description, not substance;
  - changing it needs a migration.
- Section 7 lists the tests that pin each property.

## 5. Intentional decisions left unchanged

| Decision | Why it stands |
|---|---|
| The memo is outside the fingerprint | A retry with reworded text is the same money. Section 4 documents this. |
| Group and fund are not separate fingerprint fields | They are in every posting's account key, and the domain forces them to equal the entry's. |
| A reversal can itself be reversed | It is a new entry with its own once-only constraint. The ledger owns no rule against it, and inventing one is out of scope. |
| `reverse_journal` keeps its early "already reversed" check | It gives a clear error without a write. The database constraint is the guarantee: the race test bypasses nothing and still gets exactly one. |
| No application-level tenant checks beyond RLS and triggers | RLS is the boundary. The application only turns "invisible" into "Unknown journal entry". |
| Balances recomputed from every line | Correct by construction. Checkpoints are a later ADR (section 9). |
| `member_movements` orders by entry id | Ids follow insertion order, the order postings were made. That can differ from commit order between two concurrent transactions; the running balance is still right once both commit. |
| `trial_balance(None)` sums all *visible* lines | Under a tenant it is that tenant. With no tenant it sees nothing and returns 0, which is safe but uninformative. |
| Money: Decimal, two places, floats refused, one rounding point (`allocate`) | Correct for KES. Other currencies need an ADR (memory, 2026-10-01). |
| Custody idempotency key shapes (`line:{id}:receipt`, …) | Stored keys. Renaming would break replay. |

## 6. Files changed

- `backend/contexts/ledger/application/posting.py`: B and D.
- `backend/contexts/ledger/domain/journal.py`: C, plus the fingerprint docstring.
- `backend/contexts/ledger/tests/integration/test_posting.py`: tests.
- `backend/contexts/ledger/tests/unit/test_journal.py`: test.
- `backend/tests/test_ledger_concurrency.py`: new; races on real connections.
- This document.

No migration; `makemigrations --check` is clean.

## 7. Tests added (14)

Domain:
- A reversal's cause must be its target. Different targets give different
  fingerprints. *(Fails on old code.)*

Posting and reversal (TestCase, PostgreSQL):
- A reversal retry with the same key returns the same entry.
- A reversal key reused for a different entry is refused ("different entry").
- Reversing an unknown entry gives `LedgerError` and writes nothing. *(Fails
  on old code.)*
- `load_draft` round-trips an entry and its reversal: fingerprint, cause,
  memo, line order and reversal target. *(Fails on old code.)*
- An unrelated `IntegrityError` is re-raised, not read as a reversal race or
  a replay. *(Fails on old code.)*

Queries:
- Movements come in posting order with the right running balance. The last
  balance equals `member_balances`, the trial balance is zero, and
  `FundPosition.invariant_holds`.
- Balances equal the signed sum of the lines after posts and a reversal (the
  rebuild check).

Tenants:
- The same idempotency key in two tenants makes two entries.
- Another tenant's entry cannot be reversed or loaded. Nothing is written in
  either tenant. *(Fails on old code.)*

Races (real commits, 8 connections released together):
- Eight reversals of one entry with different keys: exactly one posts, seven
  get "already reversed", and the balance is back to zero.
- Eight posts with one key and the same content: one entry, all get its id.
- Eight posts with one key and different content: one entry, seven get
  "different entry".
- Eight first uses of one account: exactly one account, all get its id.

The race tests also pass on the old code. That is expected: they pin the
database guarantee, which was already there.

## 8. PostgreSQL tests executed

- PostgreSQL 16, role `wepl_app` (RLS enforced), `manage.py test --noinput`.
- Full suite: **244 tests, OK** (230 before, plus 14).
- Ledger and the race tests alone: 44 OK.
- With `posting.py` and `journal.py` reverted, the new tests gave 2
  failures and 3 errors, as marked above.
- `makemigrations --check --dry-run`: no changes.
- `demo_custody_pilot`: runs, and the neighbour sees 0 rows.

## 9. Remaining risks

1. **Balance cost grows with history.** Every balance sums every line of
   the account. That is fine for the pilot (INFERRED from its size). A
   large group will need checkpoints, and checkpoints need an ADR, because
   a stored balance must never disagree with the lines.
2. **`wepl.ledger_open_entries` is a transaction-local string of ids.** A
   transaction that posts thousands of entries makes it long. It is
   correct but unbounded (INFERRED). Today's writers post a few entries per
   transaction.
3. **The fingerprint depends on `str(AccountKey)`.** Changing that repr, or
   adding a field to it, changes every new fingerprint. Old entries would
   then refuse an honest replay. Any change to `AccountKey` needs a
   migration that recomputes stored fingerprints. This is now stated in the
   docstring.
4. **A hand-built reversal of an unknown or foreign entry.** Passed to
   `post_journal` directly, it is refused at once by the `ledger_entry_opened`
   trigger, as a raw `IntegrityError` ("reverses an entry outside its
   tenant"), not a `LedgerError`. The money is safe. `reverse_journal`, the
   only path callers use, gives the clear `LedgerError` first.
5. **KES and two decimal places only.** By decision, not a defect.
6. **Tenant consistency of child tables** across all contexts is still the
   open ADR from the membership review (C1). The ledger's own tables are
   covered by 0005.

## 10. Before calling the ledger production-ready

1. **Checkpoint ADR**, or a measured limit showing recomputation is fast
   enough at the largest expected group.
2. **The child-table tenant-consistency ADR** (C1), so the guarantee the
   ledger has holds for every table that refers to it.
3. **A reconciliation run against a real custodian statement.** The ledger's side
   is tested, but the custodian's file format is still unknown (waiting on
   the sample).
4. **Operational checks:**
   - an alert when a nightly job finds `trial_balance` is not zero, or
     `FundPosition.invariant_holds` is false, for any fund;
   - backups that keep the append-only triggers.

   Neither exists yet.
5. **A decision** on whether reversing a reversal should be allowed. Today
   it is. It is a business rule, so it is yours to set, not the ledger's to
   invent.

---

## Addendum, 2026-10-01: the five follow-up items and the readiness assessment

Harry accepted sections 1–10 as the baseline. He asked for five items and an
assessment "based on evidence rather than theoretical concerns". Sections 1–10
above are unchanged.

### Status of section 10's items

| # | Item | Outcome | Evidence |
|---|---|---|---|
| 1 | Balance recalculation | **Measured; no checkpoints.** The threshold is 100,000 lines in one fund, watched nightly. The measurement found and fixed a real problem: two lookups scanned every tenant's rows. | ADR-0016; `benchmarks/ledger_balances.py`; ledger 0007 |
| 2 | Linked-row tenant consistency | **Decided (ADR-0017), not yet implemented.** A probe showed the gap is real. | ADR-0017 |
| 3 | Custodian reconciliation | **Waiting on the sample.** No custodian statement format or parser exists yet. | Acceptance criteria below |
| 4 | Nightly integrity check | **Built.** `check_ledger_integrity` checks every fund in every tenant, records an append-only result, audits a failure, queues an `ops.ledger_integrity_failure` alert and exits non-zero. On the demo data: 16 fund books checked, 0 failed. | ledger 0006; `test_integrity.py` (5 tests) |
| 5 | Reversal of a reversal | **Rule recorded:** allowed, and each entry is reversed at most once. | ADR-0003; `test_a_reversal_is_itself_reversible_once` |

### What the measurement found

Read and post times, on a platform of 10.2 M lines across 1,056 tenants:

| Fund | Slowest read before 0007 | Slowest read after | Post before | Post after |
|---|---|---|---|---|
| 800 lines (pilot-sized) | 31.8 ms | 6.7 ms | 425 ms | 22 ms |
| 20,000 lines | 41.0 ms | 24.2 ms | 459 ms | 17 ms |

**Before ledger 0007, cost grew with the number of groups on the platform.**
Every posting scanned every tenant's journal entries for its idempotency
key, because row-level security's `OR` cannot use an index that leads with
tenant.

**After 0007, cost depends only on the fund's own history.**
- About 0.3–1.2 µs per line.
- A pilot group's reads take a few milliseconds.
- A posting takes about 20 ms.

**The same pattern exists, unfixed, in two places outside the ledger:**
- `notify()`'s dedupe lookup: `notifications_outboxevent(tenant_id,
  dedupe_key)`, called on every alert;
- governance's `request_key`.

Each is a one-index fix (ADR-0016, Consequences).

### What a real custodian reconciliation test must prove (item 3)

The test is written when the sample arrives. It will:
1. Parse the real statement (its format decides the connector).
2. Ingest it into a fund whose books start from signed-off opening
   balances.
3. Show the statement's closing balance equals the ledger's custody cash for
   that account.
4. Show every statement line is accounted for: attributed, matched to a
   mandate, or alerted; none silently dropped.
5. Show sequence gaps and duplicates are detected on the real numbering
   scheme.
6. Show the fund position invariant holds afterwards.

Today, steps 2–6 are proven only against the simulator (custody
`test_ingestion.py`, `test_faults.py`). Until a real file is reconciled, the
claim that the ledger reconciles with the custodian is INFERRED, not CONFIRMED.

### Production-readiness assessment

**Ready for the pilot, as the ledger core.** That rests on evidence, not
design intent:
- **Invariants are database facts.** Balance, append-only history, reversal
  once and as an exact mirror, one key per entry, tenant-stamped rows. Each
  is refused by PostgreSQL itself, with a test per rule.
- **Races resolve in the database:** 8 concurrent writers per case, 4 cases.
- **Tenant isolation of what is seen** is enforced by forced RLS and tested.
- **Performance at pilot scale** is measured: milliseconds, independent of
  platform size since 0007.
- **Monitoring exists,** and passes on the demo books.
- **Tests:** 250 pass on PostgreSQL 16; the migration check is clean; the
  demo runs.

**Not production-ready until these are done.** Each is backed by a
reproduced finding, not a hypothetical:
1. **ADR-0017 implemented.** CONFIRMED: a raw write can store a row in one
   tenant that points at another tenant's group, member or fund, including
   a ledger entry through `post_journal`. Every current command prevents
   this in application code, but the database does not.
2. **A real custodian statement reconciled** (item 3). This is the custodian half
   of "the books are right".
3. **Alerts reaching a person.**
   - Today `ops.*` alerts go to the outbox and the log notifier (SMS is on
     hold).
   - The nightly command's non-zero exit is the only active alarm, and it
     needs a scheduler. Nothing schedules it yet; there is no deployment
     config in the repository.
4. **The two remaining RLS-index lookups fixed** (outbox dedupe, proposal
   request key). It is the same measured cause, and it slows every alert and
   proposal as the platform grows.
5. **The benchmark re-run on the custodian bank's production hardware and PostgreSQL
   settings.** Today's numbers come from a 4 vCPU container with default
   settings.
6. **Restore drills.** A backup must be shown to restore with every trigger
   and policy intact, then pass `check_ledger_integrity`. Not yet done.

### Update, 2026-10-01: ADR-0017 built

Blocker 1 above is closed. Harry said "lets build ADR-0017".

**What is now enforced:**
- **Composite keys:** all 30 keys between tenant-scoped tables include the
  tenant.
- **Plain-id checks:** the 6 plain-id links are checked by triggers. Each is
  installed by the context that already depends on the other one.
- **Probes:** `tests/test_linked_rows.py` repeats every probed write. Each is
  now refused, both inside a tenant and inside a cross-tenant operation.
- **Guard test:** the build fails if a new key between tenant-scoped tables
  leaves out the tenant.

**Evidence the probes test this rule:**
- With the four migrations held back, the probe tests fail (8 failures,
  4 errors).
- With the migrations in place, every refusal names an ADR-0017 key or
  check.

**Other checks:**
- The existing demo data passed every new key check when migrated.
- The migrations reverse cleanly.

Blockers 2–6 stand.

