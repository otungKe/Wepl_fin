# ADR-0011: Membership, titles and capabilities are separate

- **Status:** Proposed. Answers Harry's "Domain Review — Membership Roles"
  (2026-09-30).
- **Changes:** ADR-0008 (who may correct the books) and the voting rules. The
  mechanism in ADR-0008 stays; "official" is replaced by an explicit
  capability.

## Question

Do chair, treasurer and secretary belong in the foundational domain? Harry
asked for three concepts to be kept apart:

1. **Membership:** is this person in this group (ACTIVE or LEFT)?
2. **Title:** an optional organisational label, only if the product needs it.
3. **Capability:** what the member may do.

He also said: "Do not assume that an organizational title is equivalent to a
permission."

## What the code did before this ADR

`Membership.role` was one of CHAIR, TREASURER, SECRETARY or MEMBER. The only
thing the software ever did with it was collapse it into a single yes/no,
`is_official` (any of the first three). That one flag controlled three
powers:

| Power | Where |
|---|---|
| Counts toward the "officials" approval tier of a withdrawal | `governance/domain/voting.py` |
| May cancel a withdrawal request someone else made | `governance/application/proposals.py` |
| May correct the books (attribute a payment, explain an outflow, sign off opening balances, maker-checker) | `custody/domain/authority.py` (ADR-0008) |

Nothing distinguished a chair from a treasurer. The title was a permission in
disguise, which is exactly what Harry warned against.

## Evidence

| Claim | Class | Evidence |
|---|---|---|
| Groups need **some members to have authority others do not**: approving withdrawals up to a limit, correcting records, signing off opening balances | **CONFIRMED** (by the pilot artefacts Harry commissioned) | Constitution template §5: "Withdrawal up to KES __: e.g. any 2 officials"; §7: opening balances "signed off by the treasurer"; pilot plan: "The treasurer signs off the opening balances", "Ask the treasurer once about unknown payers". |
| **Who holds that authority differs by group**, and is a group decision | **STRONGLY INFERRED** | The template leaves "Who approves" blank per row, with "e.g." answers, and has a "Change of officials" row. The strategy doc's segments differ: chamas have "Treasurer + members", structured organisations have "Treasurer, board" and "committee approvals". |
| Groups **use titles** (Chair, Treasurer, Secretary) and members recognise them | **STRONGLY INFERRED** for Kenyan chamas; **UNKNOWN** for other segments | Constitution template §1 "Officials" table; interview scripts "A. Treasurer / chair" and "B. Member (not an official)". Churches and associations are described with a "board" and "committee", not these three titles. |
| The software must **behave differently per title** (a chair may do X that a treasurer may not) | **ASSUMPTION**; no evidence | No pilot document, workflow or requirement names a power held by one title and not another. The template's "e.g. any 2 officials" treats them as interchangeable. |
| **A title should imply permissions** | **Contradicted** by the evidence | The original WEPL did this ("treasurer treated as admin" in `FinancialPermissions`) and it produced two permission systems that disagree (reverse-engineering report, C5). |
| Bank signatories at I&M are the same people as those with approval capability | **UNKNOWN** | The custody design has the treasurer initiate and a second official authorise in I&M's own channels. Whether WEPL's approvers must equal I&M's mandate holders is for I&M to answer. WEPL does not model bank signatories. |
| Secretary records minutes; officials post announcements | **INFERRED** from the strategy doc and template §6 ("Minutes are kept by: Secretary") | These workflows are not built. When they are, they get their own capability (for example `POST_ANNOUNCEMENT`), not a title check. |

## Decision

**Roles are removed from the domain.** In their place:

1. **Membership** stays as it was: status ACTIVE or LEFT. A member who has
   left holds no capability, whatever was granted.
2. **Title** is an optional free-text label on the membership (up to 60
   characters). "Chair", "Treasurer", "Patron", "Committee member" or blank.
   It is shown to people. **The software never checks it.**
3. **Capabilities** are owned by governance, because deciding who may do what
   is part of how a group governs itself. They are explicit, per member, and
   append-only:

   | Capability | Lets the member | Replaces |
   |---|---|---|
   | `approve_payout` | count toward approval tiers reserved for designated approvers | "officials" tier |
   | `cancel_payout` | cancel an open withdrawal request someone else made | official may cancel |
   | `correct_records` | attribute a payment, explain an outflow, sign off opening balances (two different holders) | official may correct |

   Every grant or revocation is a new `governance_capabilitychange` row
   (tenant-scoped with forced RLS, append-only in PostgreSQL) and an audit
   event. What a member may do now is the latest change per capability.

4. **The constitution names the set, not the titles.** The approval tier is
   `"approvers": "designated"` (members holding `approve_payout`) or
   `"members"` (any active member). Constitutions already stored with
   `"officials"` still read, as `designated`.

Only the capabilities that current workflows check exist. `VIEW_FINANCIALS`,
`MANAGE_MEMBERS` and `MANAGE_GOALS` from Harry's examples are not added yet:
today every member sees the group's records (transparency is the product) and
members and goals are managed by the operator. Each is added with the
workflow that needs it.

## Harry's five questions, answered

1. **Which workflows need titles?** None. Titles are a display label for
   onboarding, statements and the constitution document.
2. **Why would they be domain concepts?** They are not. The domain concept is
   *authority*, which is now capabilities.
3. **Do all groups use them?** Chamas typically do (STRONGLY INFERRED); other
   segments use boards and committees (INFERRED). Free text covers both.
4. **Do they determine permissions?** No. A test proves a member titled
   "Chair" with no grants cannot approve, cancel or correct.
5. **How are different structures represented?** By granting capabilities to
   whichever members the group's constitution names: a chama grants its
   three officials; a church grants its finance committee; a small group can
   grant everyone `approve_payout` and use a "designated" tier of 2.

## Nothing that was enforced is lost

- Migration `governance 0004` grants every active former chair, treasurer and
  secretary all three capabilities, so each keeps exactly the power the role
  gave. `communities 0004` copies the role into the title, and
  `communities 0005` drops the role.
- Every rule in ADR-0008 still holds, restated in capabilities: an active
  member of the account's own group holding `correct_records`; never in their
  own favour; opening balances need two different holders; the audit actor is
  the corrector's phone number.
- The voting rules are unchanged apart from the set's name.

## Consequences

- **Who grants?** In the pilot, the operator records the grants the signed
  constitution names (the same trust model as ADR-0008: no login yet). When
  login lands, granting and revoking become a governed decision of the group
  (a proposal the constitution's "Change of officials" rule approves), and
  the operator path is removed.
- **Notifications** about an unidentified payer (`payer.unidentified`) are
  for members holding `correct_records`, not "the treasurer".
- **Revisit** when a real requirement names a power one title has and another
  does not. Even then the answer is a capability, not a title check.
