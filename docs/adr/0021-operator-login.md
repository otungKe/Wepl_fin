# ADR-0021: Operator login (WEPL staff)

- **Status:** **Proposed** (2026-10-04). Step 5 of the plan Harry approved
  ("Proceed as suggested", 2026-10-04). Harry has been asked whether
  operators or members come first; this draft assumes operators.
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

## Decision (proposed)

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

## Not decided (UNKNOWN)

- What screen operators use. There is no back-office front end; this builds
  the login API and protects the setup actions behind it.
- Password hashing: Django's default PBKDF2 unless Harry or the bank's
  security review asks for Argon2 (an extra dependency).
- Where the authenticator secret key is kept in production (an encrypted
  column with a key from the environment is the default proposed).
- Member login (phone code, then PIN) waits on the SMS provider.

## Alternatives

- **JWT bearer tokens.** Rejected for operators: they cannot be revoked
  before they expire, and the original WEPL signed member and operator
  tokens with one key and never tested that one family is refused by the
  other's endpoints.
- **Django admin users as operators.** Rejected: it mixes a framework's
  superuser model with business authority and has no step-up.
