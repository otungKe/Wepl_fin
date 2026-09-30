---
name: wepl-security
description: Who may do what in Wepl_fin. Covers what is enforced today
  (official-only corrections, no self-benefit, maker-checker, votes, group
  isolation, append-only history, boot guards, log redaction), what is not
  built (login, KYC, operators, tenancy), and the rules to follow when they
  land. Use when touching a command that takes `by`, `actor` or a voter,
  settings, logging, notifications, or anything that decides who may act.
---

# Wepl_fin security

The standing rules are in `docs/architecture/engineering-guidelines.md`
(rules 23–25, 30 and 32). ADR-0008 records the current authorization model.
Parts are adapted from the original WEPL repo's `wepl-security` skill; they
are marked **(borrowed)** and describe how to build what does not exist here
yet.

## What is enforced today

**Only these are enforced; everything else is a gap.** Each has a test.

| Rule | Where | Test |
|---|---|---|
| Voting eligibility: active member of the group; no vote by the proposer, payee or charged member; officials-only tiers | `governance/domain/voting.py` | `governance/tests/` |
| A vote cannot be changed; repeating the same vote is a no-op | `governance/application/proposals.py` | `governance/tests/` |
| A payout needs a single-use mandate; anything else alerts every member | `governance/domain/mandate.py`, `custody/domain/matching.py` | `custody/tests/integration/test_ingestion.py` |
| **Corrections need an active official of the account's group** | `custody/domain/authority.py` | `custody/tests/*/test_authority.py` |
| **No correction in your own favour** (attributing a payment to yourself) | same | same |
| **Opening balances need two different officials** (maker-checker) | same | same |
| Nothing done in one group touches another group's money or decisions | application checks (ADR-0005) | `tests/test_isolation.py` |
| Financial and audit history cannot be edited or deleted, even with SQL | PostgreSQL triggers (ADR-0003) | ledger, custody and audit tests |
| Every business action has an audit record with an operation id | `audit.public.record` / `operation` | throughout |
| **Refuse to boot** with DEBUG off and the dev secret, or with DEBUG off and the simulated bank | `config/settings.py` | `tests/test_settings_guards.py` |
| **Logs carry no phone numbers or names** | `notifications/domain/redaction.py` | `notifications/tests/unit/test_redaction.py` |

### How a command names who is acting

- **Member and official commands take a membership id:**
  - voting uses `voter_id`;
  - proposing uses `proposer_id`;
  - corrections and opening balances use `by` and `confirmed_by`.

  The command loads the membership and refuses before writing anything. The
  audit actor is that member's phone number.
- **Never add a new money-affecting command that takes a free-text `actor`.**
  A string cannot be checked against anything. That was the gap ADR-0008
  closed.
- **Setup commands still take a free-text `actor`:** `create_group`,
  `add_member`, `adopt_constitution` and `link_external_account`. They are
  operator actions, reachable only from management commands and tests. They
  wait for operator identity (below).
- **Refusals raise the context's own error** (`CustodyError`,
  `GovernanceError`) with "Not authorised: …". Tests assert that nothing was
  written: no line resolution, no journal, no mandate claimed.

## What is not built (do not assume it exists)

- **Authentication.** A membership id passed as `by` is trusted as given. It
  says *which* member is claimed, not that the caller *is* that member.
  Today that is safe only because there is no HTTP surface (just `/health/`).
  **The first endpoint that accepts a command must take the actor from the
  session, never from the request body.**
- **Operator (concierge / back-office) identity.** Operators are not members
  and have no account type.
- **KYC.**
- **Tenancy.** An open question (ADR-0005). Group isolation is enforced in
  application code only; there is no row-level security.
- **Rate limiting.**

## Rules for when login lands

### Two identities, never mixed (borrowed)

| | Member | Operator |
|---|---|---|
| Identifier | phone number (`identity.Msisdn`) | work email |
| Credential | OTP, then a PIN | password provisioned by an admin, forced change, TOTP step-up |
| Authorization | membership role in *this* group | capabilities (below) |

- An operator is never a member and never votes.
- Sign the two token families with **different keys** or distinguish them by
  audience. The original WEPL signed both with one `SECRET_KEY` and never
  tested that one family is refused by the other's endpoints. Write that test
  first.

### Other rules

- **Staged tokens (borrowed).** A phone-verified but unfinished session may
  only set a PIN. The default permission is "fully active session". Test that
  an intermediate token is refused by every money command; the original WEPL
  never did.
- **An OTP bypass for staging (borrowed)** must have a boot guard like the one
  in `config/settings.py`, tested the same way: a fresh interpreter plus
  `django.setup()` and a non-zero exit. Never turn a guard into a warning.
- **Operator capabilities (borrowed).**
  - Dotted capability strings (`custody.attribute`, `ledger.reverse`) are
    mapped to roles in code and enforced server-side.
  - Maker-checker is object-level: an `*.approve` capability never lets
    someone approve their own request.
  - Sensitive actions need a fresh step-up, with no exemption for superusers.
  - Every operator action is audited.
- **KYC is a case ledger, not a status field (borrowed).** Decisions append
  to a case timeline; the profile status is a projection.
- **Policies fail closed.** An action with no registered rule is refused.
- **Personal data.** Members see counterparty names masked; operators see
  them in full, and that access is audited. Logs never carry phone numbers,
  names or account numbers: route anything new through
  `notifications/domain/redaction.py` or a similar pure masker.

## Forbidden shortcuts

- Taking the acting member or operator from request input once login exists.
- A new money command with a free-text `actor`.
- Relaxing a boot guard, or making it conditional on anything but DEBUG.
- Running the simulator with DEBUG off. There is no flag to allow it.
- Letting an official correct in their own favour "because the group is
  small": another official does it.
- Logging a payload that has not been redacted.
- Checking authorization only in a frontend.

## Before you merge a change that decides who may act

1. The pure rule is in a `domain/` module, with unit tests for each refusal.
2. An integration test covers each unauthorized actor: an ordinary member, a
   former official, another group's official, an unknown id, self-benefit.
3. Each refusal leaves nothing written. `Scenario.assert_sound` still holds.
4. The audit record names the real actor.
5. Record any new security rule or shortcut in an ADR, and add it to the
   table above.
