# WEPL money core: architecture overview

**What it is.** WEPL keeps a trusted register of who owns what in a group's
pooled money, and the approvals (mandates) that authorise every payout. Each
day it proves that register against the account where the money is actually
held. In the pilot WEPL never holds money: each group keeps it in its own Chama
Account at the custodian bank (ADR-0006).

## Contexts

```
                  ┌────────────┐
                  │  custody   │  statement lines → accounting decisions → reconciliation
                  └─────┬──────┘
         ┌──────────────┼──────────────┬───────────────┐
         ▼              ▼              ▼               ▼
   ┌──────────┐   ┌───────────┐  ┌──────────┐   ┌───────────────┐
   │governance│   │  ledger   │  │communities│  │ notifications │
   └────┬─────┘   └───────────┘  └────┬─────┘   └───────────────┘
        └─────────────► communities ◄─┘
                          identity ◄── communities
   audit ◄── every context        shared_kernel (Money) ◄── every context
```

Arrows point from a caller to the public surface it depends on. What each
context owns and does not own is in ADR-0002 and in each context's
`__init__.py`.

## Layers inside a context

| Layer | Question it answers | Example |
|---|---|---|
| `domain/` | What is true about the business? | `JournalDraft` refuses an unbalanced entry; `ineligibility()` says why a voter may not approve |
| `application/` | What operation are we performing? | `propose_withdrawal`, `ingest`, `reconcile` |
| `infrastructure/` | How do we talk to the outside world? | ORM models, migrations, connectors, notifiers, commands |
| `contract.py` / `public.py` | What may other contexts depend on? | `MandateView`, `post_journal` |

## The core workflow

1. **Ingest.** The custody `ingest` use case takes custodian lines. Each line is
   handled in its own transaction, with the account row locked. A line seen
   before is ignored. A line resent with different details raises a conflict
   alert.
2. **Decide the accounting.** Custody's domain decides what each line means:
   - **Deposit.** It goes to a member, found by member code, by a remembered
     payer or by the member's own number. Otherwise it is held as
     unattributed.
   - **Interest and charges.** They are shared pro rata or retained, as the
     constitution says.
   - **Withdrawal.** It must match an issued mandate, by reference and exact
     amount, or as the only candidate by amount and payee. Governance's
     `execute_mandate` claims the mandate with a conditional UPDATE, so it
     pays out once. With no match, the amount goes to `unexplained_out` and
     every member is alerted.
3. **Post.** The decision is a `JournalDraft`, and `ledger.post_journal` posts
   it. The journal key comes from the line, so a retry cannot double-post.
4. **Reconcile.** WEPL's cash is compared with the custodian's running
   balance. Missing sequence numbers and unaccounted lines are also checked.
   Any difference raises an alert.
5. **Correct.** Members granted `correct_records` (ADR-0011) can attribute a held payment (the payer is
   remembered) or explain an unmatched payout with a mandate approved after
   the fact. Each correction is a new entry and a new resolution; nothing is
   edited.

## Cross-cutting

- **Audit.** Governance and custody decisions write append-only audit records
  carrying the group and an operation id. Journal entries, queued
  notifications and reconciliation runs carry the same operation id, so one
  workflow can be traced end to end.
- **Notifications.** An outbox row is written in the same transaction as the
  change that caused it. Rows are delivered at least once, with dedupe keys,
  and failures are retried on a later pass. SMS is on hold; the default
  notifier logs.
- **Tenancy.** Each group is its own tenant (ADR-0010). Every operation runs
  in an explicit tenant context. Tenant
  data is isolated by forced PostgreSQL row-level security, and application
  checks keep groups apart inside a tenant (ADR-0009, ADR-0005).

## Evidence for the custodian bank (custody design §8)

| Claim | Where it is shown |
|---|---|
| The ledger cannot be silently wrong | ADR-0003's three layers; `contexts/ledger/tests`; `tests/test_properties.py` checks that books equal the bank to the cent over random histories on a faulty feed |
| Pay-ins are never lost or double-counted | `contexts/custody/tests/integration/test_faults.py`: duplicates, reordering, withheld lines healed by the sweep, conflicting resends, reprocessing after a crash |
| No payment moves without a mandate | `contexts/custody/tests/integration/test_ingestion.py`; the property test checks that every outflow is matched or alerted |
| One group cannot touch another's money | `tests/test_isolation.py` |
| Auditability | `custody.line_trail` goes from a bank transaction to its journal entries and mandate; `audit.history` gives every governance decision |
| Architecture stays as designed | `tests/test_architecture.py` |
| Demo | `python manage.py demo_im_pilot` |

## Not yet built

- **Payouts through the custodian bank's APIs** (Model C, a `payments` context).
- **The real custodian statement format:** waiting on a sample export.
- **Contributions:** cycles, arrears and goals.
- **Authentication, HTTP API and backoffice.**
- **Institutions:** organizations with explicit, per-purpose, audited access
  grants to the groups they serve (ADR-0010).
- **Scale and concurrency:** cross-process concurrency tests, load tests.
- **Group life:** chat, announcements, meetings, vault.
