# ADR-0012: Membership owns the relationship, and nothing else

- **Status:** Proposed, except the return policy (section 6), which Harry
  **accepted and locked** on 2026-09-30. Answers Harry's "Review: Membership
  Domain Model" and "Membership Return Policy".
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

**Superseded by [ADR-0013](0013-founding-a-group.md):** `Segment` was then
removed from the core model altogether; the pilot tracker keeps it.

**Change (at the time):** `Segment` moves to `communities/domain/group.py`, next to the
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
| Is LEFT terminal? | **Yes.** A returning person gets a **new** membership with a new code. The old membership and its code keep meaning the earlier spell, so old payments, balances and audit records stay unambiguous. | **CONFIRMED**: Harry locked it (section 6) |

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

**Concurrency is tested.** `tests/test_concurrency.py` runs eight joins at
once on separate connections, with committed transactions, and checks the
codes come out M01 to M08.
- Without the group row lock, the same test fails with a duplicate code.
- It is a plain `unittest.TestCase`, because `TransactionTestCase` cannot
  clean up tables that refuse truncation.
- Its rows live in a tenant of their own, and Django runs it after all its
  own test cases.

## 6. Return policy (accepted by Harry, 2026-09-30)

> A person's membership is a time-bounded membership spell. If a person
> leaves and later rejoins, the returning person receives a new Membership
> record and a new member code. The previous membership remains permanently
> `LEFT` and its member code is never reused.

### How each part is enforced

| Rule | Application | Database | Test |
|---|---|---|---|
| LEFT is terminal | `leave_group` refuses a second leave (`ensure_can_leave`); no use case sets ACTIVE | trigger refuses LEFT → ACTIVE | `communities/tests/integration/test_membership.py` |
| Rejoining creates a new membership | `add_member` always inserts; it never updates an old row | a membership's group, person, code and joining time never change | same, `test_repeated_leaving_and_returning` |
| One ACTIVE spell per person per group | `add_member` refuses | partial unique index on (group, person) where active | `test_one_active_spell_per_person` |
| Codes are never reused | allocation from `Group.last_member_sequence` | counter never decreases; memberships never deleted; `(group, member_code)` unique | `test_codes_come_from_the_groups_counter_not_a_count`, `test_memberships_are_never_deleted_or_re_pointed` |
| Allocation is safe under concurrency | the group row lock | unique `(group, member_code)` as a backstop | `tests/test_concurrency.py` |
| Identity is stable across spells | `register_person` finds the person by phone number and keeps their original name | unique phone number on `identity_person` | `test_a_returning_person_keeps_their_identity_even_under_another_name` |

### What history points at

Every record that concerns a member points at the **membership** (the
spell), by id. None points at the person or the code, so each record stays
with the spell it happened in:

| Record | Reference | Consequence for a returning member |
|---|---|---|
| Ledger member accounts and journal lines | `member_id` = membership id | balance of the old spell stays on it; the new spell starts at 0 |
| Statement-line resolutions | `membership_id` | payments before leaving stay with the old spell |
| Proposals, approvals, charged member | membership id | a vote cast as M04 stays M04's |
| Capability grants | membership id | authority does not carry over; the group grants again |
| Payer memory (`PayerMapping`) | membership id | see below |
| Audit events | target = membership id; actor = phone number | who did it is the person; what it concerned is the spell |
| Reports | code, name and **status** per spell | M04 (left) and M06 (active) show separately |

### Two gaps this review found, now fixed

1. **A payment quoting an ended code could be moved to another spell.**
   - Attribution only knew active members. A deposit quoting "M04" after
     Kiprono left fell through to his phone number, and was credited to his
     new spell M06.
   - Now attribution sees every spell. A quoted code of an ended spell holds
     the money as unattributed for a person to decide.
   - Tests: `custody/tests/unit/test_domain.py` and
     `custody/tests/integration/test_returning_member.py`.
2. **A payer remembered for an old spell could never be remembered again.**
   - `PayerMapping` is unique per phone number, and remembering used
     `get_or_create`. A spouse's number mapped to M04 was ignored after
     Kiprono left, which is correct. But it could not be re-pointed to M06,
     so the treasurer would have been asked every time.
   - Now a correction that attributes such a payment to an active spell
     re-points a mapping whose spell has ended.
   - A mapping to a spell that is still current is left alone, as before.
   - Nothing is remembered for an ended spell.

### Not decided here

- **A leaver's unsettled balance.** The constitution says it is paid out
  after leaving. Until it is, it sits on the old spell and is excluded from
  pro-rata interest sharing, which only counts active members. Whether a
  leaver should share interest until paid out is **UNKNOWN**, and belongs
  to the ledger and contributions work, not membership.
- **Attributing a late payment to an ended spell by hand** is allowed. A
  corrector may decide that money paid before someone left belongs to that
  spell. That is not a reactivation.

## Open question for Harry

1. **Joining approval.** Should the product itself ever handle requests to
   join (PENDING), or does admission stay a group decision recorded by the
   operator?
