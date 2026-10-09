# ADR-0015: A fund's lifecycle

- **Status:** **Accepted** by Harry on 2026-10-01 ("As recommended"). It
  comes from [the fund review](../architecture/review-funds-module.md), D2.
- **Builds on:** ADR-0013 (funds are opened separately; 0..n per group) and
  ADR-0004 (cross-context references).

## Decision

```text
open_fund ──▶ OPEN ──rename_fund──▶ OPEN       (audited, from → to)
                │
                └─close_fund──▶ CLOSED          final; never reopens, never deleted
```

| Question | Decision | Why |
|---|---|---|
| Rename? | Yes, while open, audited with `from` and `to`. | Every record points at the fund's id, so a rename breaks nothing, and the audit keeps the old name. The name is the constitution's (§3), so who may rename follows who may change the constitution, once authorization exists. |
| Close? | Yes, only when it is empty (below). A closed fund takes no new proposal, custodian account or name. | Groups wind pools up (a welfare kitty, a one-off collection). An empty fund is the only state in which ending it cannot strand money. |
| Reopen? | No. A group that needs the pool again opens a new fund. A closed fund's name is free again. | This mirrors membership spells (ADR-0012): old records keep meaning the old fund. |
| Delete? | Never. PostgreSQL refuses it. | Proposals, mandates and custodian accounts refer to a fund by foreign key, but the ledger refers to it by a plain number, which would not stop a deletion. |

## "Empty", and who decides it

Each context refuses closing for what it owns. Communities does not reach
into the others.

| Condition | Owner | Enforced by |
|---|---|---|
| Nothing is held: every ledger account of the fund is at zero, in every currency | ledger | `close_fund` asks `ledger.public.fund_holds_nothing` under the fund's row lock; every journal entry takes a share lock on its fund and is refused once it is closed (communities 0019, ADR-0026) |
| No open proposal and no unexecuted (issued) mandate | governance | a trigger on closing (governance 0005). A new proposal takes a share lock on its fund, so it and closing serialise. |
| No fund transfer naming it that is open, or approved but not booked (ADR-0024) | governance | the same trigger (governance 0009). A new transfer takes a share lock on both funds. |
| No linked custodian account that is still open | custody | a trigger on closing (custody 0004, 0007). Linking takes a share lock on the fund. |

**Consequences:**
- **No posting can reach a closed fund.** ~~Every posting comes through a
  linked custodian account, and a closed fund can have none.~~ That stopped
  being true when one account came to hold all of a group's funds
  (ADR-0023): a fund without an account of its own receives pay-ins quoting
  its code. Since ADR-0026, PostgreSQL refuses any journal entry into a
  closed fund and serialises it with closing (communities 0019).
- **A fund with a custodian account closes once that account is closed.**
  See the addendum below (2026-10-04).
- **Communities and the ledger still don't hold each other's tables.**
  Governance's and custody's triggers sit on the side that already depends
  on communities.

## Alternatives

- **Closing as a soft delete (a flag nobody checks).** Rejected: the other
  contexts would keep using the fund.
- **Communities checking proposals and accounts itself.** Rejected: it would
  make communities depend on governance and custody, which already depend on
  it.

## Addendum (2026-10-04): closing a custodian account

This builds the "unlink" step the consequences above left open. The rules
below are the thread's design; Harry approved building this step
("Proceed as suggested", 2026-10-04) and accepted the details (2026-10-05).

- **`custody.close_external_account(account, by, confirmed_by)`** records
  that the fund's money is no longer held there. The account row stays;
  `closed_at` is set once.
- **It refuses unless** a reconciliation run at closing, under the
  account's lock, shows:
  - the custodian's latest running balance is zero (an account with no
    line at all also counts as empty);
  - WEPL's cash agrees with it;
  - no sequence number is missing and the running balance follows;
  - every line is accounted for;
  - no alert on any of its lines is open (for example money that left
    without a mandate).
- **Two members granted `correct_records` sign it off,** as for opening
  balances. Closing moves no money; the bank closes the real account
  through its own process.
- **Fetch the final statement first.** Closing reconciles what has been
  received; it does not call the custodian.
- **After closing (database-enforced, custody 0007):**
  - the account never reopens, nothing else about it changes, and it is
    never deleted;
  - it takes no new statement line;
  - the fund can close.
- **If the custodian later reports a new transaction** on a closed account,
  ingest refuses it, `sync_accounts` fails naming the account, and the
  nightly digest shows the job failure. The bank's collections calls find
  no open account and are refused.
- **Open (UNKNOWN):** whether the same bank account may later back another
  fund. Today it cannot: an account number is linked at most once.

