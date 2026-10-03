# Design: each group governs how its leavers' balances are treated

- **Date:** 2026-09-30.
- **Requested by:** Harry, "Resolve: Financial Treatment of a Leaver's
  Unpaid Balance".
- **Status:** design only; no code has changed. Read against commit
  `6aac001`.
- **Direction (CONFIRMED, Harry):** each group chooses, in its constitution
  at onboarding, between `SHARES_UNTIL_PAID` and `FROZEN_AT_LEAVING`. No
  universal behaviour is hard-coded.

## What the codebase actually has

Everything in this table is **CONFIRMED** by the code.

| Fact | Evidence |
|---|---|
| The constitution is governance's: versioned and append-only. Each version is a full `rules` document with `effective_from` = the moment it was adopted. Proposals keep the version they were made under. | `governance_constitution`; `adopt_constitution` |
| The constitution already holds two financial sharing rules, `interest` and `bank_charges`, each `pro_rata` or `retained`. | `ConstitutionRules` |
| **Those two rules silently default to `pro_rata` if a constitution omits them.** That is the kind of implicit default Harry wants to avoid. | `ConstitutionRules.parse` |
| "Interest" means **interest the bank credits** to the custodian account (a statement line of kind INTEREST). "Charges" means **bank charges** (kind CHARGE). | `custody/domain/statement.py` `LineKind` |
| Not modelled at all: investment return, profit allocation, fund appreciation, penalties, arrears, arrears charges. | nothing in the code |
| There is a third, separate kind of sharing: a **pro-rata payout**, where group spending is shared by balance under a mandate with `Allocation.PRO_RATA`. It is not a charge. | `custody/domain/accounting.py` |
| Custody applies the sharing when it ingests a statement line. It uses the **current** constitution at processing time, not the version in force when the bank posted the line. | `bookkeeping.rules(ea)` → `current_rules` |
| Custody shares only among **active** members, so today a leaver is frozen by accident. `LeaverSharingTests` pins this. | `bookkeeping.sharing_facts` |
| Pro-rata weights use `max(balance, 0)`, so a member who owes money neither earns interest nor bears charges. | `share_pro_rata` |
| A membership records no time of leaving. Only the audit event has one. | `communities_membership` |
| Journal entries and statement-line resolutions do not record which constitution version was applied. | `ledger_journalentry`, `custody_lineresolution` |
| There is no contributions or arrears context. | `backend/contexts/` |
| Constitution changes are recorded by the operator, from a paper sign-off. They are not yet a governed vote. The template asks for a "Change to this constitution" rule (e.g. two-thirds of members). | `adopt_constitution`; pilot template §5 |

## A. Recommended domain model

```text
Governance
  Constitution (versioned, append-only)
    rules
      approvals …
      interest:            PRO_RATA | RETAINED           (exists)
      bank_charges:        PRO_RATA | RETAINED           (exists)
      leaver_balances:     SHARES_UNTIL_PAID | FROZEN_AT_LEAVING   (new, required)

Communities
  Membership   ACTIVE → LEFT, plus left_at        (the fact that a spell ended, and when)

Sharing computation  (custody today; a contributions/accrual context later)
  reads: the constitution version in force, balances (ledger), spells (communities)
  decides: who shares this interest or charge, and how much
  records: which constitution version it applied

Ledger
  the postings: the source of truth for every balance
```

- **The leaver policy is a rule of the constitution, next to `interest` and
  `bank_charges`.**
  - This is **STRONGLY INFERRED**. The constitution already owns the other
    two sharing rules, and the pilot template's §7 already asks each group
    for its leaving rule.
- **Nothing goes on `Membership` except `left_at`.** *When* a spell ended is
  a fact about the membership (**CONFIRMED** need: `FROZEN_AT_LEAVING`
  cannot know which events came after leaving without it). *What follows
  financially* is not a membership fact.

## B. Policy representation (proposed, not implemented)

```python
# governance/domain/rules.py
class LeaverBalances(StrEnum):
    """What a former member's balance in a fund does after their spell ends,
    until it is settled."""
    SHARES_UNTIL_PAID = "shares_until_paid"   # keeps sharing interest and bank charges by balance
    FROZEN_AT_LEAVING = "frozen_at_leaving"   # takes part in no interest or bank charge dated after left_at

@dataclass(frozen=True)
class ConstitutionRules:
    ...
    interest: SharingRule
    bank_charges: SharingRule
    leaver_balances: LeaverBalances     # required: parse() refuses a new constitution without it
```

```python
# the sharing computation's domain (pure)
@dataclass(frozen=True)
class Spell:
    membership_id: int
    left_at: datetime | None         # None while active

def sharers(spells, balances, *, event_at, treatment: LeaverBalances) -> list[int]:
    """Who takes part in an interest credit or bank charge dated event_at.
    Active spells always do. A spell that ended by event_at takes part only
    under SHARES_UNTIL_PAID, and only while it still holds a positive balance."""
```

- **Nothing that is computed is stored in the constitution.** It holds the
  choice; the ledger holds the balances.
- **Reading constitutions adopted before this change.** They have no
  `leaver_balances`. They read as `FROZEN_AT_LEAVING`, labelled "as applied",
  because that is what the code actually did while they were in force.
  - This is not a policy choice. It reproduces history.
  - New versions must state the rule explicitly.

## C. Bounded-context ownership

| Concept | Owner | Class |
|---|---|---|
| Constitution | Governance | CONFIRMED |
| Interest rule, bank-charges rule | Governance (constitution) | CONFIRMED |
| **Leaver-balance policy** | Governance (constitution) | STRONGLY INFERRED (recommended) |
| Applying interest and charges to members | Custody today (`accounting.interest` and `charge`), because both come from the bank statement | CONFIRMED |
| Contributions (obligations, what is due) | A contributions context, **not built** | UNKNOWN until built |
| Arrears | Contributions, **not built** | UNKNOWN |
| Former member's entitlement | Derived: the ledger balance of the old spell, less any debts the constitution says to net | balance CONFIRMED; netting UNKNOWN |
| Settlement calculation (amount due) | Contributions once built. Until then, the balance shown by the ledger. | INFERRED |
| Settlement approval and payment | Governance (a withdrawal charged to the old spell, then a mandate) and custody (matching the payout) | CONFIRMED path |
| Ledger posting | Ledger (`post_journal`, the only door) | CONFIRMED |
| When a spell ended (`left_at`) | Communities | CONFIRMED need; field to add |

Contributions is not the default owner of the policy. The policy is a
*governing rule* of the group. Contributions or custody *apply* it.

## D. Lifecycle, and where the two policies diverge

```text
Onboarding: constitution v1 adopted, leaver_balances chosen explicitly
John joins          → M07 ACTIVE
John contributes    → deposits attributed to M07 (custody, then ledger)
Position exists     → ledger balance of (fund, M07) = 5,000
John leaves         → M07 LEFT, left_at = t1   (communities; no financial event)
Bank credits interest dated t2 > t1
    sharing computation takes the constitution version in force at t2 and asks sharers(...):

    SHARES_UNTIL_PAID                       FROZEN_AT_LEAVING
    M07 has 5,000 > 0 and the rule          M07 ended at t1 ≤ t2
    keeps it → M07 takes part               → M07 does not take part
    M07's share of interest is credited     M07 stays at 5,000;
    and its share of bank charges debited   the others share it all
                                ↑ the only point of divergence
Settlement: a governed withdrawal charged to M07 (Allocation.MEMBER) → mandate
           → payout matched → ledger debits M07's account
    SHARES: M07's balance reaches 0, so the spell stops taking part from then on
    FROZEN: M07's balance reaches 0 (it had stopped taking part at t1)
```

- **An interest line dated before t1 but processed after t1** is shared as
  of its **bank posting date**. M07 took part as an active member either
  way. Today's code gets this wrong: it reads membership status at
  processing time.
- **Pro-rata payouts (group spending) are not covered** by either choice. A
  leaver's balance is not spent by the group's later decisions today, and
  whether it should be is an open question (see F).

**Returning member.** John rejoins as M08.
- M08 is a separate spell with its own ledger account, starting at 0.
- Under `SHARES_UNTIL_PAID`, M07 and M08 take part independently, each by
  its own balance.
- Nothing moves between them unless a person records an explicit transfer.
  Whether a transfer is allowed is open (F).

## E. Historical treatment

**Principle:** a posted outcome never changes. The ledger is append-only,
so a new constitution cannot rewrite a past posting (CONFIRMED). The risk
is in *which rule a future posting uses*.

1. **Every sharing posting records the constitution version it applied.**
   - Today it does not.
   - Put the version on the statement-line resolution (custody) and in the
     journal entry's cause or memo. Then any outcome can be recomputed from
     the balances, the spells and that version.
2. **Use the version in force at the event's own date** (the bank's posting
   date), not the version current when the line happens to be processed.
   - This fixes the gap in the table at the top.
   - It needs a query, `rules_in_force(group_id, at)`.
3. **Which version governs a leaver after the policy changes is a decision,
   not a technical one.** ADR REQUIRED. The two candidates are:
   - **Terms fixed at leaving.** A leaver keeps the treatment in force at
     their `left_at` until settled. That is fair to the leaver, since the
     rules can't change after they are gone. It needs the leaving version to
     be recorded per spell, and the sharing computation reads it.
   - **The rule in force at each event.** A policy change applies from its
     effective date to every leaver not yet settled. This is simpler, and
     groups already live this way for interest and charges.

   Either way, every outcome stays reproducible, because each posting
   records the version it used (point 1).
4. **Effective dates.**
   - Today `effective_from` is the adoption moment.
   - Whether a change can take effect later, for example at the next cycle,
     is UNKNOWN.

## F. Open questions (the codebase cannot establish these)

1. **Terms fixed at leaving, or the rule at each event?** (E3.)
2. **What "settled" means for `SHARES_UNTIL_PAID`.** Balance at zero? The
   settlement mandate executed? Partial payouts? INFERRED: balance at zero.
3. **Recoverable balances.** A leaver who *owes* the group, with a
   negative balance or arrears: does anything accrue on it? Today negative
   balances neither earn nor bear anything (CONFIRMED). Penalties and
   arrears don't exist yet.
4. **Netting at settlement:** "balance paid out … less any loan owed"
   (template §7). Who computes it, and against what? That is contributions
   and loans, neither of which exists.
5. **Group spending (pro-rata payouts) after leaving.** Does a leaver's
   balance bear a share of spending the group decides after they left?
   Today it does not. This is a separate question from charges.
6. **Changing the policy.** Who may change it, and by what approval? The
   template's "Change to this constitution" row suggests a governed vote,
   but the product has no vote for it yet. When does a change take effect?
   Does it apply to existing leavers? (Partly E3.)
7. **Every member has left.** Today it raises "no active members to share
   this among". Under `SHARES_UNTIL_PAID` a leaver with a balance would take
   part. Under `FROZEN_AT_LEAVING`, where does the interest go: retained, or
   held unattributed?
8. **Should `interest` and `bank_charges` also become required choices,**
   rather than defaulting to `pro_rata`? This is the same "no implicit
   default" principle.
9. **Time weighting.** Interest is split by balances at the time of the
   credit, not over the period it accrued (CONFIRMED). Is that acceptable to
   groups and to the custodian bank? UNKNOWN.

## G. ADRs required before implementation

1. **ADR-0014 (update): leaver balances are a constitution choice.**
   - `SHARES_UNTIL_PAID` or `FROZEN_AT_LEAVING`, chosen explicitly at
     onboarding, with no default.
   - Old constitutions read as "frozen, as applied".
   - This is Harry's decision; it records it.
2. **Which constitution version governs a financial event** (E2 and E3):
   the event-date rule, terms fixed at leaving or not, and the version
   recorded on every sharing posting.
3. **Changing financial rules:** who, what approval, and the effective date
   (F6, E4).
4. **Settlement:** what "paid" means, netting, recoverable balances, and
   group spending after leaving (F2 to F5). It could wait for the
   contributions context, but it must be decided before the first leaver
   is settled in the pilot.

## H. Implementation impact (for later; nothing changed now)

| Area | Change |
|---|---|
| Governance domain | `LeaverBalances` enum; `ConstitutionRules.leaver_balances`, required for new versions; old versions read as frozen; optionally `interest` and `bank_charges` also required (F8) |
| Governance application | `rules_in_force(group_id, at)`; adoption refuses a constitution without the choice; later, a governed change use case (ADR 3) |
| Communities | `Membership.left_at`, set by `leave_group`. PostgreSQL enforces that it is set if and only if LEFT and never changes. `MembershipView.left_at`. Backfilled from the `member.left` audit events. |
| Custody (the sharing computation until contributions exists) | a pure `sharers(...)` rule; apply the version in force at the line's posting date; record that version on `LineResolution` and in the journal cause or memo; pro-rata *payouts* stay as they are pending F5 |
| Ledger | none: postings stay the source of truth; balances stay derived |
| Events | none new: leaving stays a non-financial event, audited as today |
| Onboarding | the demo and `Scenario` state `leaver_balances` in the constitution they adopt; a constitution without it is refused |
| Tests | per policy: a leaver shares (or does not) in interest and charges dated after `left_at`; a line dated before leaving but processed after is shared with the leaver as a member; a settled leaver stops sharing; a returning member's spells stay separate; a negative balance earns nothing; a policy change leaves every past posting unchanged and records the new version on new ones; a constitution without the choice is refused; old constitutions reproduce "frozen". `LeaverSharingTests` is replaced by these. |
