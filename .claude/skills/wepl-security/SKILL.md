---
name: wepl-security
description: Who may do what in Wepl_fin. Covers what is enforced today
  (explicit capabilities, never titles; no self-benefit, maker-checker, votes, group
  isolation, append-only history, boot guards, log redaction, operator
  sign-in), what is not built (member login, KYC), tenant isolation by
  row-level security,
  and the rules to follow when they
  land. Use when touching a command that takes `by`, `actor` or a voter,
  settings, logging, notifications, or anything that decides who may act.
---

# Wepl_fin security

The standing rules are in `docs/architecture/engineering-guidelines.md`
(rules 23–25, 30 and 32). ADR-0008 records the current authorization model;
ADR-0011 separates membership, title and capability.
Parts are adapted from the original WEPL repo's `wepl-security` skill; they
are marked **(borrowed)** and describe how to build what does not exist here
yet.

## Membership, title, capability (ADR-0011)

- **Membership** answers "is this person in this group" (ACTIVE or LEFT).
- **Title** ("Chair", "Treasurer", blank) is a label. **Never check it.**
- **Capability** answers "may they do this". Governance owns them
  (`governance.public.grant`, `revoke`, `holds`, `holders`), append-only and
  audited. Today: `approve_payout`, `cancel_payout`, `correct_records`.
- A new permission is a new `Capability` added with the workflow that needs
  it, and checked with `holds(...)`. Never add `if title == ...`, never
  derive a capability from a title, and never add a role enum.

## What is enforced today

**Only these are enforced; everything else is a gap.** Each has a test.

| Rule | Where | Test |
|---|---|---|
| Voting eligibility: active member of the group; no vote by the proposer, payee or charged member; "designated" tiers need `approve_payout` | `governance/domain/voting.py` | `governance/tests/` |
| Cancelling someone else's withdrawal request needs `cancel_payout` | `governance/application/proposals.py` | `governance/tests/integration/test_capabilities.py` |
| Capabilities are explicit grants, append-only, audited; a member who left holds none | `governance/application/capabilities.py` | same |
| A vote cannot be changed; repeating the same vote is a no-op | `governance/application/proposals.py` | `governance/tests/` |
| A payout needs a single-use mandate; anything else alerts every member | `governance/domain/mandate.py`, `custody/domain/matching.py` | `custody/tests/integration/test_ingestion.py` |
| **Corrections need an active member of the account's group holding `correct_records`**; a title grants nothing | `custody/domain/authority.py` | `custody/tests/*/test_authority.py` |
| **No correction in your own favour** (attributing a payment to yourself) | same | same |
| **Opening balances need two different `correct_records` holders** (maker-checker) | same | same |
| Nothing done in one group touches another group's money or decisions | application checks (ADR-0005) | `tests/test_isolation.py` |
| **Tenant isolation by forced PostgreSQL row-level security**; fails closed without a context; cross-tenant access declared and audited | `contexts/tenancy`, `persistence/tenancy.py` (ADR-0009) | `tests/test_tenancy.py` |
| **The app's database role cannot bypass RLS** | `tenancy.E001` system check | `tests/test_tenancy.py` |
| **A row only ever refers to rows of its own tenant**, for any role in any mode (foreign keys ignore RLS, so the tenant is part of every key) | composite keys and plain-id checks (ADR-0017) | `tests/test_linked_rows.py` |
| Financial and audit history cannot be edited or deleted, even with SQL | PostgreSQL triggers (ADR-0003) | ledger, custody and audit tests |
| Every business action has an audit record with an operation id | `audit.public.record` / `operation` | throughout |
| **Refuse to boot** with DEBUG off and the dev secret, or with DEBUG off and the simulated bank | `config/settings.py` | `tests/test_settings_guards.py` |
| **Logs carry no phone numbers or names** | `notifications/domain/redaction.py` | `notifications/tests/unit/test_redaction.py` |
| **Operators sign in** with a provisioned account: password, then an authenticator code (RFC 6238, each code once); staged sessions reach nothing until finished; 30-minute idle and 12-hour limits; five failures lock for 15 minutes and end open sessions; identical answers for unknown email, wrong password and locked | `contexts/operators` (ADR-0021) | `operators/tests/` |
| **Operator capabilities fail closed**, by role in code; sensitive ones need a code from the last 10 minutes | `operators/domain/capabilities.py` | same |
| **Production refuses to boot without `WEPL_OPERATOR_KEY`** (authenticator secrets are encrypted with it) | `config/settings.py` | `tests/test_settings_guards.py` |

### How a command names who is acting

- **Member commands take a membership id:**
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
  operator actions, reachable only from code and tests. When each gets an
  endpoint, it takes the operator from `operators.public.authenticate(token,
  capability)` and audits `operator:<id>`; never a string from the request.
- **Refusals raise the context's own error** (`CustodyError`,
  `GovernanceError`) with "Not authorised: …". Tests assert that nothing was
  written: no line resolution, no journal, no mandate claimed.

## What is not built (do not assume it exists)

- **Member authentication.** A membership id passed as `by` is trusted as given
  (inside the tenant context, which RLS enforces). It
  says *which* member is claimed, not that the caller *is* that member.
  Today that is safe only because there is no HTTP surface (just `/health/`).
  **The first endpoint that accepts a command must take the actor from the
  session, never from the request body.**
- **A back-office screen.** Operators have the sign-in API and the inbox
  endpoint only.
- **KYC.**
- **User-scoped row security.** People (`identity.Person`) are USER_SCOPED
  and have no RLS until login gives a user context (ADR-0009).
- **Rate limiting.**

## Operator sign-in (built, ADR-0021)

- Protect an operator endpoint with
  `authenticate(request.COOKIES.get(COOKIE, ""), OperatorCapability.X)`
  and answer `NotSignedIn` with a plain 401. Add a capability to
  `domain/capabilities.py` (and `STEP_UP` if sensitive) with the endpoint
  that needs it.
- Server commands that act as an operator call
  `operator_at_console(email, code, capability)`.
- Under `ATOMIC_REQUESTS`, a failure that must be remembered (a wrong
  password or code) is returned, never raised, or the count rolls back.

## Rules for when member login lands

### Two identities, never mixed (borrowed)

| | Member | Operator |
|---|---|---|
| Identifier | phone number (`identity.Msisdn`) | work email |
| Credential | OTP, then a PIN | password provisioned by an admin, forced change, TOTP step-up |
| Authorization | capabilities granted in *this* group (ADR-0011) | operator capabilities (below) |

- An operator is never a member and never votes.
- Sign the two token families with **different keys** or distinguish them by
  audience. The original WEPL signed both with one `SECRET_KEY` and never
  tested that one family is refused by the other's endpoints. Write that test
  first.

### Other rules

- **The tenant comes from the session.** Once login lands, the session's
  membership decides the tenant context, never a request parameter.

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
- Letting a corrector correct in their own favour "because the group is
  small": another holder does it.
- Treating a title as a permission (ADR-0011).
- Logging a payload that has not been redacted.
- Checking authorization only in a frontend.

## Before you merge a change that decides who may act

1. The pure rule is in a `domain/` module, with unit tests for each refusal.
2. An integration test covers each unauthorized actor: an ordinary member,
   a member with a title but no grant, a former holder, another group's
   holder, an unknown id, self-benefit.
3. Each refusal leaves nothing written. `Scenario.assert_sound` still holds.
4. The audit record names the real actor.
5. Record any new security rule or shortcut in an ADR, and add it to the
   table above.
