# Architecture of the money core

## What it is

A modular monolith (Django 5.2 LTS, Python 3.12, PostgreSQL 16). One process,
one database, clear module boundaries that a test enforces. No Redis, Celery
or WebSockets: PostgreSQL does the queueing (an outbox table drained with
`SELECT … FOR UPDATE SKIP LOCKED`), so there is one system to back up,
restore and reason about. Django 5.2 is the long-term-support release,
supported until April 2028.

## Custody model

Pilot: **Model A**. Each group owns an I&M Chama Account. Payouts are made by
the officials in I&M's own channels, under the bank's dual authorisation. WEPL
cannot move money; it provides *detective* control: every outflow on the
statement must match a mandate the group approved in WEPL, or every member is
alerted.

Target: **Model C**, I&M banking-as-a-service, where WEPL submits the payout
itself and the mandate becomes a *preventive* control. The mandate, matching
and ledger code are the same in both; only the connector changes.

## Modules and dependencies

```
connectivity ──► governance ──► parties ──► platform_core
      │                                          ▲
      └────────► ledger ─────────────────────────┘
simulator (tests and demo only; nothing imports it)
```

`tests/test_architecture.py` fails the build if an import crosses these lines,
if production code imports the simulator, or if anything other than
`ledger/services.py` writes journal rows.

## The ledger

Accounts are keyed by fund and purpose:

| Purpose | Normal side | Meaning |
|---|---|---|
| `custody_cash` | debit | Money in the group's account at the custodian |
| `member_interest` | credit | What the group owes each member |
| `unattributed_in` | credit | Pay-ins we cannot yet tie to a member |
| `unexplained_out` | debit | Payouts with no mandate: alerted, awaiting explanation |
| `retained` | credit | Interest or charges the constitution keeps at group level |

**Invariant:** `cash = member interests + unattributed + retained − unexplained out`,
which holds because every entry balances.

What the database enforces on its own (migrations `ledger/0002`,
`*/0002_append_only`):

- Every journal entry has at least two lines and balances per currency. This is
  a deferred constraint trigger, checked at commit, so no code path, shell
  session or future module can commit an unbalanced entry.
- Line amounts are positive (CHECK constraint).
- Journal entries, lines, accounts, statement lines, line resolutions,
  approvals, constitutions, reconciliation runs and the audit log reject
  UPDATE, DELETE and TRUNCATE. Corrections are new rows (reversals, new
  resolutions, new constitution versions), so history is never lost.
- Posting is idempotent by key (`line:{id}:{outcome}`), so a retried job or a
  duplicate bank notification cannot double-post.

## From bank line to ledger

1. `ingest` receives lines from a connector. Each line is processed in its own
   transaction with the account row locked. A line already seen is ignored; a
   line resent with *different* details raises a statement-conflict alert and
   is not posted.
2. Deposits are attributed by member code in the reference, then by a
   remembered payer phone number, then by the member's own number; otherwise
   they are held as unattributed until the treasurer says who paid (once:
   the mapping is remembered).
3. Withdrawals are matched to an issued mandate by its `WM…` reference and
   exact amount, or, without a reference, to the single issued mandate with
   that amount and payee. The mandate is claimed with a conditional UPDATE, so
   it can pay out once only. No match: the amount goes to `unexplained_out`,
   an alert is raised and every member is notified.
4. Interest and charges are shared across members in proportion to their
   balances, or retained, as the constitution says. Splits use the
   largest-remainder method, so they add up to the cent.
5. `reconcile` compares WEPL's cash with the bank's running balance, checks for
   missing bank sequence numbers and unprocessed lines, and records the result.
   Any difference raises an alert.

## Evidence for I&M (custody design §8)

| Claim | Where it is shown |
|---|---|
| The ledger cannot be silently wrong | Database triggers above; `tests/test_ledger.py`; `tests/test_properties.py` generates random histories and checks the books equal the bank to the cent |
| Pay-ins are never lost or double-counted | `tests/test_faults.py`: duplicates, reordering, withheld lines healed by the sweep, conflicting resends |
| No payment moves without a mandate | `tests/test_connectivity.py`; the property test asserts every outflow is matched or alerted |
| Auditability | Every entry records its cause (statement line); every resolution records its mandate or member and who acted; the audit log records every governance decision |
| Demo | `python manage.py demo_im_pilot` follows the 20-minute script |

Not yet covered, and planned: payout submission and "unknown result" handling
for Model C, a real I&M statement format (waiting on a sample export),
concurrency tests across processes, load tests, and group life.
