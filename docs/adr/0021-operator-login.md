# ADR-0021: Operator login (WEPL staff)

- **Status:** **Accepted** (Harry, 2026-10-05: "Accepted"), with the role names
  `support`, `onboarding` and `admin` as built. Step 5 of the plan Harry
  approved ("Proceed as suggested", 2026-10-04). Harry chose **operators
  first** (2026-10-04).
- **Builds on:** ADR-0008 (who may act before login), ADR-0009 (tenancy),
  ADR-0011 (capabilities, never titles), ADR-0020 (operator inbox), and the
  `wepl-security` skill's "Rules for when login lands".

## Context

- Setup actions (`create_group`, `add_member`, `adopt_constitution`,
  `link_external_account`) and the operator inbox take a typed name as the
  actor. Nothing checks it. The audit trail records whatever was typed.
- The pilot is run by WEPL staff with each group's officials. The bank will
  ask who did each back-office action and how that person proved it.
- Member login needs SMS codes, and the SMS provider is on hold. Operator
  login needs no SMS.

## Decision

1. **Operators are their own identity, never members.** A new `operators`
   context owns `Operator`: work email (unique, case-insensitive), name,
   active flag, password hash, authenticator (TOTP) secret. An operator
   never votes and is never a membership.
2. **Provisioned, never self-registered.** `create_operator` (a management
   command run on the server) creates one with a one-time password. The
   first sign-in forces a password change and authenticator enrolment.
   Deactivating an operator ends their sessions.
3. **Sign-in is staged.** Email and password give a *partial* session that
   can only complete the authenticator step (or change the password /
   enrol). Only a *full* session reaches anything else. A test proves every
   other endpoint refuses a partial session.
4. **Server-side sessions, not bearer tokens.** A session can be revoked at
   once. Cookie: HttpOnly, Secure, SameSite=Strict, its own name. Idle
   timeout 30 minutes; absolute limit 12 hours. Member sessions, when they
   come, use a different cookie and are refused by operator endpoints, and
   the reverse; that test is written first.
5. **Lockout.** Five failed attempts lock the operator for 15 minutes.
   Every success, failure and lock is audited. The response never says
   whether the email exists.
6. **Operator capabilities fail closed.** Dotted strings mapped to
   operator roles in code (for example `groups.setup`, `custody.link`,
   `custody.close`, `operations.inbox`). An action with no registered rule
   is refused. Maker-checker stays object-level: nobody approves their own
   request.
7. **Step-up for sensitive actions.** Founding a group, linking or closing
   a bank account, adopting a constitution and reading across groups need an
   authenticator code entered in the last 10 minutes.
8. **The actor comes from the session.** Setup commands take an operator
   id, not a string; the audit actor is `operator:<id>`. An operator acting
   for a group enters that tenant through an explicit, audited reason
   (ADR-0009); they never get standing cross-tenant access.
9. **Management commands stay for break-glass.** They require
   `--operator EMAIL` naming an active operator and a current authenticator
   code, and are audited the same way.

## As built (2026-10-04)

- Context `operators`; endpoints under `/operators/`: `sign-in`,
  `password`, `authenticator/begin`, `authenticator/confirm`, `code`,
  `step-up`, `sign-out`, `me`, and `inbox` (the operator inbox, ADR-0020).
- Sessions are rows of `OperatorSession`; the cookie `wepl_operator` holds
  a random token and only its SHA-256 is stored. Path `/operators/`,
  HttpOnly, Secure, SameSite=Strict. POST bodies must be JSON.
- Roles and capabilities (`domain/capabilities.py`): `support` reads the
  inbox; `onboarding` also sets groups up and links or closes bank
  accounts; `admin` has everything, including managing operators. The
  inbox, setup, bank-account and operator-management capabilities all need
  a code entered in the last 10 minutes.
- Authenticator codes follow RFC 6238 (tested against its vectors); a code
  is accepted once. Secrets are encrypted with `WEPL_OPERATOR_KEY`
  (Fernet, from the `cryptography` package, a new dependency). Production
  refuses to boot without the key.
- Wrong passwords and wrong codes both count toward the lock. Locking ends
  the operator's open sessions.
- **The sign-in log is the operators context's own append-only table**,
  not the audit trail: the audit trail is tenant-scoped, and sign-in
  happens outside any group. What an operator does inside a group is
  audited there with actor `operator:<id>`.
- `create_operator` creates the first admin with no operator named (only
  while there are none); after that an admin names themselves with
  `--by EMAIL --code CODE`. `deactivate_operator` and `operator_inbox`
  work the same way.
- **Not yet moved behind sign-in:** `create_group`, `add_member`,
  `adopt_constitution`, `link_external_account` and
  `close_external_account` are still reached only from code and tests with
  a typed actor; there is no HTTP endpoint for them yet. Each moves behind
  `authenticate(token, capability)` when its endpoint is built.

## Not decided (UNKNOWN)

- What screen operators use. There is no back-office front end; this builds
  the login API and protects the setup actions behind it.
- Password hashing: Django's default PBKDF2 unless Harry or the bank's
  security review asks for Argon2 (an extra dependency).
- Where `WEPL_OPERATOR_KEY` lives in production (a secrets manager on the
  host) and how it is rotated.
- Member login (phone code, then PIN) waits on the SMS provider.

## Alternatives

- **JWT bearer tokens.** Rejected for operators: they cannot be revoked
  before they expire, and the original WEPL signed member and operator
  tokens with one key and never tested that one family is refused by the
  other's endpoints.
- **Django admin users as operators.** Rejected: it mixes a framework's
  superuser model with business authority and has no step-up.
