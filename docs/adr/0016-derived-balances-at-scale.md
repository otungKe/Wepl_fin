# ADR-0016: Balances stay derived from full history; checkpoints wait for a measured threshold

- **Status:** Proposed (2026-10-01). Follows Harry's instruction: "measure it
  against realistic projected transaction volumes before introducing
  checkpoints… If a threshold is identified, document the decision in an ADR."
- **Evidence:** `backend/benchmarks/ledger_balances.py`, run against
  PostgreSQL 16 as the application role, under row-level security, through
  the ledger's public reads.

## Context

ADR-0003 derives every balance from journal lines; nothing is stored. The
cost of a read therefore grows with the history it sums. The open question
was whether that cost becomes a material problem at volumes WEPL can expect,
and so whether balance checkpoints (a stored, verified balance up to some
entry) are needed now.

## What was measured

**Setup.**
- 4 vCPU container; PostgreSQL 16 with default settings (128 MB shared
  buffers); one client; warm cache; median of 7 runs.
- **Platform:** 1,056 tenants, 105,284 accounts, 5.1 million entries, 10.2
  million journal lines. That is far more than the pilot, so that the
  platform's size would show if it mattered.
- **Each entry has two lines,** as custody posts. Nine in ten are
  contributions and one in ten a payout.
- **The posting column** includes the commit and the commit-time balance
  check.

### Finding 1: before this ADR, cost grew with the *platform*, not the fund

The first two runs were made without the indexes this ADR adds.

| Platform size | Read, 800-line fund | `post_journal` |
|---|---|---|
| 4.2 M lines, 4.3 k accounts | 2.8–6.3 ms | 163–175 ms |
| 10.2 M lines, 105 k accounts | 16.5–31.8 ms | 415–459 ms |

**Cause (CONFIRMED by `EXPLAIN ANALYZE`).**
- Row-level security adds `tenant_id = current OR cross_tenant` to every
  query.
- PostgreSQL cannot use that `OR` to enter an index that leads with
  `tenant_id`.
- The ledger's two lookups had no other index:
  - the idempotency key lookup: unique on `(tenant, key)`;
  - accounts by fund: unique key leading with tenant.
- So every posting scanned every tenant's entries (254 ms for one key
  lookup), and every read scanned every tenant's accounts. A small group
  would have slowed down as other groups joined.

**Fix (ledger 0007):**
- an index on `ledger_journalentry(idempotency_key)`;
- an index on `ledger_account(fund_id)`.

No behaviour changes; RLS still filters every row.

### Finding 2: with the indexes, cost depends only on the fund's own history

Same 10.2 M-line platform, after ledger 0007:

| Fund history | Lines | Members | `fund_position` | `member_balances` | `account_balance` | `trial_balance` | `fund_holds_nothing` | `member_movements` (one member) | `post_journal` |
|---|---|---|---|---|---|---|---|---|---|
| 30 members monthly, 1 year | 800 | 30 | 4.7 ms | 2.9 ms | 4.0 ms | 3.3 ms | 4.5 ms | 6.7 ms | 21.7 ms |
| 200 members weekly, 11 months | 20,000 | 200 | 24.2 ms | 16.4 ms | 12.5 ms | 20.2 ms | 22.3 ms | 9.7 ms | 16.9 ms |
| 500 members weekly, 3.5 years | 200,000 | 500 | 236 ms | 94 ms | 60 ms | 101 ms | 142 ms | 13.0 ms | 13.6 ms |
| 1,000 members weekly, 17 years | 2,000,000 | 1,000 | 1,375 ms | 677 ms | 614 ms | 1,176 ms | 556 ms | 65 ms | 15.1 ms |

Posting stays flat at 14–22 ms whatever the history. Reads grow linearly at
about 0.3–1.2 µs per line. `member_movements` stays cheap because it reads
one member's account.

## Projected volumes

These are assumptions, to be confirmed with I&M's pilot list:
- **Pilot groups:** chamas of 10–50 members contributing monthly, at most
  weekly. That is roughly 300–6,000 lines per fund per year.
- **Growth:** the largest group in view is about 200 members contributing
  weekly, roughly 23,000 lines per year.

At those volumes the slowest read is under about 25 ms, and posting is about
20 ms.

## Decision

1. **No checkpoints, caches or stored balances now.** The measurement shows
   no material problem at projected volumes. Full-history derivation stays
   the only source of a balance.
2. **Threshold: 100,000 journal lines in any one fund.**
   - At about that size the heaviest reads (`fund_position`,
     `trial_balance`) reach about 100 ms on this hardware.
   - `member_balances`, which custody's sharing computation calls per
     interest or charge line, is about 50 ms.
   - Reaching the threshold takes:
     - a 30-member monthly group: about 125 years;
     - a 200-member weekly group: about 4 years.
3. **The threshold is watched, not guessed.** The nightly integrity check
   (ledger 0006) records each fund's line count.
4. **When any fund passes 100,000 lines,** or a production read of the
   ledger exceeds 100 ms at the 95th percentile on I&M's hardware:
   - re-run the benchmark there;
   - write the checkpoint ADR.

   That ADR must keep the journal the source of truth. A checkpoint would
   be a verified summary of committed lines, checked by the nightly job,
   and never written by posting.
5. **Every lookup the ledger makes without a tenant predicate needs an
   index that does not lead with `tenant_id`,** for the reason in finding 1.
   The same applies across the platform (see Consequences).

## Alternatives considered

- **Checkpoints now.** They would add a second representation of every
  balance that could disagree with the lines, for no measured benefit.
  Rejected until the threshold.
- **A running balance column on each line.** That is a stored balance under
  another name. It needs ordering and locking per account, and a reversal
  or a late line rewrites the meaning of every later row. Rejected.
- **Adding `tenant_id = current_tenant` to each ledger query instead of
  indexes.** This works, but every new query must remember it. The
  indexes cover any query. Rejected as the primary fix.

## Consequences

- Reads at pilot scale are a few milliseconds, independent of how many other
  groups exist. Posting costs about 20 ms.
- **The same RLS-and-index pattern exists outside the ledger** (CONFIRMED
  from the catalogue; not changed here, because it is outside the ledger):
  - `notifications_outboxevent(tenant_id, dedupe_key)`: `notify()` looks a
    dedupe key up on every call;
  - `governance_proposal(tenant_id, request_key)`.

  Each would scan every tenant's rows as the platform grows. Each needs the
  same one-line index fix.
- The benchmark is checked in, so the threshold can be re-measured on
  production hardware with one command.
