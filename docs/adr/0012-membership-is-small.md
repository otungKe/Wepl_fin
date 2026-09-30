# ADR-0012: Membership owns the relationship, and nothing else

- **Status:** Proposed. Answers Harry's "Review: Membership Domain Model"
  (2026-09-30).
- **Builds on:** ADR-0011 (a title is a label; capabilities live in governance).

## Decision in one picture

```text
Person (identity)
   ↕
Membership (communities)
   ├── group
   ├── status        ACTIVE → LEFT, never back
   ├── member_code   stable business identifier, never reused
   └── title         optional label, "" when none
```

For every proposed field, the test is: *is this a fact about the person's
membership in this group, or a fact another context owns?* Payments,
contributions, balances, capabilities, notifications, KYC and login all
belong elsewhere and stay there.

## 1. `Segment` is a fact about the group, not the membership

| Question | Finding | Class |
|---|---|---|
| What does it describe? | The kind of group. The constitution template's cover page asks once per group: "**Segment:** Savings/investment chama / Welfare or association / Collection". It is stored on `communities_group`, never on a membership. It only sat in `membership.py` by file placement. | **CONFIRMED** |
| Can one member be in several at once? | Yes, and that is modelled by **funds**, not segments. The template's §3 lists "Main savings" and "(optional) Welfare" as two funds of one group. The strategy doc says the same: "a savings fund plus a welfare kitty". | **CONFIRMED** |
| Does any rule depend on it? | No. The strategy doc says the core is "group-type-agnostic" and "archetypes remain unnecessary". Nothing in the code branches on it. | **CONFIRMED** (code), **CONFIRMED** (strategy) |
| Why keep it at all? | The pilot compares segments: pilot plan V5, "Which segment is strongest?", and the pivot rule "narrow to that segment". | **CONFIRMED** |
| Is it one value per group? | The template offers a single choice. A group that is really two kinds is not covered. | **INFERRED** |

**Change:** `Segment` moves to `communities/domain/group.py`, next to the
group it describes. Its docstring says it is a pilot comparison label and
that no rule may branch on it. Nothing else changes: no fund- or
contribution-level category is added, because no workflow needs one yet.

## 2. `MembershipStatus`: ACTIVE and LEFT, and LEFT is final

| Question | Finding | Class |
|---|---|---|
| Is leaving a real requirement? | Yes. Constitution template §7: "Leaving: notice ___ days; balance paid out within ___ days, less any loan owed". | **CONFIRMED** |
| INVITED or PENDING? | §7 asks "Joining: who approves new members?", so groups decide admissions. In the pilot that happens outside the software, and the operator records the result. No in-product invitation or request exists. | **UNKNOWN**: not added |
| SUSPENDED? | Nothing in the pilot documents mentions suspension. | No evidence: not added |
| REJECTED? | Only meaningful with PENDING. | Not added |
| Can someone leave and come back? | Nothing says they cannot. People rejoin chamas. | **INFERRED** |
| Is LEFT terminal? | Decided here: **yes**. A returning person gets a **new** membership with a new code. The old membership and its code keep meaning the earlier spell, so old payments, balances and audit records stay unambiguous. | Decision (ASSUMPTION about the rejoin rule, flagged for Harry) |

**Change:**
- A `leave_group` use case exists now. Before this, LEFT could only be set
  by hand. It is audited, and the member's capabilities lapse with it.
- Settling the leaver's balance is a ledger and governance matter, not
  membership's.
- PostgreSQL refuses LEFT → ACTIVE.

## 3. `title`

| Question | Finding | Class |
|---|---|---|
| Optional? | Yes. Most members have none. | **CONFIRMED** (template: only the officials table names people) |
| Group-specific? | Yes. It lives on the membership, so the same person can be "Treasurer" in one group and nothing in another. | **CONFIRMED** (model) |
| Can it change? | Yes. The template has a "Change of officials" approval row. | **STRONGLY INFERRED** |
| Does changing it affect authorization? | No. Capabilities do that (ADR-0011). A test shows a title change leaves capabilities untouched. | **CONFIRMED** (code) |
| Is title history needed? | No rule reads past titles. Who was *authorised* when is already kept by governance's append-only capability changes. Knowing the label at a past date is useful for people reading history. | **INFERRED** |

**Change:**
- A `set_title` use case exists. Each change writes an audit event with
  `from` and `to`, which is enough history.
- No title-history table is added. If governance ever needs a title at a
  point in time, that is a signal the title has become a permission, which
  ADR-0011 forbids.

## 4. `clean_title()`

- **"" is the one representation of "no title"**, in the domain, the
  database (`NOT NULL DEFAULT ''`) and the views.
- `None`, `""` and whitespace-only all become `""`. They are normalised,
  not rejected: a blank form field means "no title".
- `"  Group   Treasurer  "` becomes `"Group Treasurer"`.
- More than 60 characters is refused.
- All of these are tested in `communities/tests/unit/test_membership.py`.

## 5. Member codes are stable business identifiers

| Question | Finding | Class |
|---|---|---|
| Display label or business identifier? | **Business identifier.** Members quote it as the payment reference, and custody attributes deposits by it (`custody/domain/attribution.py`). A code on an old payment must keep meaning the same membership. | **CONFIRMED** |

**What was wrong:** `add_member` allocated `count(memberships) + 1`. The
group row lock made it safe against two members joining at once. But it was
correct only while no membership was ever deleted, and nothing enforced
that: deleting M05 would have handed M05 to the next person.

**Change:**
- **Allocation is separate from formatting.**
  - `Group.last_member_sequence` is a counter. `add_member` increments it
    under the group row lock, the same lock that already serialised joins.
  - `member_code(sequence)` stays a pure formatter.
  - Migration 0006 backfills each counter from the highest existing code.
- **PostgreSQL enforces the identity rules** (migration 0006):
  - a membership is never deleted or truncated;
  - its group, person, code and joining time never change;
  - the counter never decreases;
  - moving a row to another tenant was already refused by row-level
    security.
- **The rejoin rule:** a new membership and a new code (section 2).
  - Attribution matches only *active* members' codes. A payment quoting a
    former code is therefore held as unattributed, and a person decides.
  - Old references still resolve: `members(group, active_only=False)`
    lists every membership with its code.

**Not tested:** true cross-connection concurrency. It needs a
`TransactionTestCase`, whose flush the no-truncate triggers refuse (see the
wepl-testing skill). The guarantee rests on the group row lock plus a
counter that the database will not let decrease. A test proves codes come
from the counter and not from a count.

## Open questions for Harry

1. **Rejoining.** Is "new membership, new code" right? The alternative is
   reactivating the old membership, which would make a code span two spells
   of membership with a gap.
2. **Joining approval.** Should the product itself ever handle requests to
   join (PENDING), or does admission stay a group decision recorded by the
   operator?
