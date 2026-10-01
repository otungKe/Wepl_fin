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
| Nothing is held: every ledger account of the fund is at zero, in every currency | ledger | `close_fund` asks `ledger.public.fund_holds_nothing` under the fund's row lock |
| No open proposal and no unexecuted (issued) mandate | governance | a trigger on closing (governance 0005). A new proposal takes a share lock on its fund, so it and closing serialise. |
| No linked custodian account | custody | a trigger on closing (custody 0004). Linking takes a share lock on the fund. |

**Consequences:**
- **No posting can reach a closed fund.** Every posting comes through a
  linked custodian account, and a closed fund can have none. INFERRED from
  the code: custody is the ledger's only caller.
- **A fund that has ever had a custodian account cannot close yet.** Custody
  has no "unlink" use case. Building one is custody's next step when a group
  first winds up a fund; it needs its own rules (final statement,
  reconciliation at zero).
- **Communities and the ledger still don't hold each other's tables.**
  Governance's and custody's triggers sit on the side that already depends
  on communities.

## Alternatives

- **Closing as a soft delete (a flag nobody checks).** Rejected: the other
  contexts would keep using the fund.
- **Communities checking proposals and accounts itself.** Rejected: it would
  make communities depend on governance and custody, which already depend on
  it.
