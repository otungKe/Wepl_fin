# ADR-0008: Who may act on the books before login exists

- **Status:** Proposed

## Context

There is no authentication yet (rule 24). Until 2026-09-30, the corrections
(`attribute_payment`, `explain_outflow`) and `record_opening_balances` took a
free-text `actor` string, so anyone who could call them could move money
between member claims and have any name written to the audit trail. Those are
the three commands that change what members are owed without a vote.

The simulated I&M bank was also installed by default. Nothing stopped it
running in a production process, beside real accounts.

## Decision

1. **The actor is a membership, not a string.** The three commands take `by`,
   a membership id. The pure rule is `custody/domain/authority.py`, and it
   refuses the actor unless they are an **active official of the account's
   own group**. Officials are the chair, treasurer and secretary.
   *Amended by [ADR-0011](0011-membership-titles-and-capabilities.md):*
   "official" now means "holds the `correct_records` capability". A title
   grants nothing. Every rule below is otherwise unchanged.
2. **No correction in your own favour.** An official cannot attribute a
   payment to themselves. The same rule governance applies to voting.
3. **Maker-checker for opening balances.** `record_opening_balances` needs
   two different officials, `by` and `confirmed_by`. Both are audited.
   Officials usually hold balances themselves, so the second signature is the
   control here, not a self-benefit block.
4. **`explain_outflow` needs one official.** The mandate it cites already
   carries the group's approval.
5. **The audit actor is the official's phone number.** The same convention
   governance uses for votes.
6. **The simulated bank cannot run with DEBUG off.** Settings raise at boot
   unless `WEPL_ENABLE_SIMULATOR=0`. This sits beside the existing
   `DJANGO_SECRET_KEY` guard, and both are tested in a fresh interpreter.
7. **Logs never carry phone numbers or names.** `LogNotifier` masks them
   (`notifications/domain/redaction.py`). The outbox row keeps the full
   message.

## What this does not solve (UNKNOWN / not built)

- **Identity.** `by` is trusted as given. It proves *which* membership is
  claimed, not that the caller *is* that person. That needs authentication:
  member phone + OTP, per the wepl-security skill.
- **Setup commands still take a free-text actor:**
  - `create_group`
  - `add_member`
  - `adopt_constitution`
  - `link_external_account`

  They are operator actions. There is no operator identity yet, and they are
  only reachable from management commands and tests, with no HTTP surface.
- **Tenancy (ADR-0005)** is still enforced in the application only.

## Alternatives considered

- **Keep the string and check it against a role list.** Rejected: a name
  cannot be checked against anything.
- **Require a governance vote for every correction.** Rejected for the pilot.
  Attribution is routine treasurer work, and the unmatched-outflow alert
  already goes to every member.
- **An operator (concierge) identity now.** Deferred: that is the ops identity
  with capabilities that the security skill describes, and it arrives with
  login.

## Consequences

- Every correction names a real official of the right group. An ordinary
  member, a former official, another group's official, an unknown id or a
  self-credit is refused before anything is written. Tested in
  `custody/tests/integration/test_authority.py`.
- A production deploy that forgets `WEPL_ENABLE_SIMULATOR=0` fails at boot
  instead of running a fake bank.

## What would make us revisit

- Authentication lands: `by` then comes from the session, never from input.
- Operator accounts land: setup commands take an operator with a capability.
- I&M asks for maker-checker on attribution as well.
