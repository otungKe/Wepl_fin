# ADR-0019: The bank's collections service on each group's own account

- **Status:** **Accepted** (Harry, 2026-10-04).
  - Harry returned to one account per group on 2026-10-04 (ADR-0006 stands:
    WEPL never holds money).
  - He confirmed that any account, a chama account included, can use the
    bank's collections service (Business Connect).
  - The decision is accepted. The request format and the signing
    mechanism are still settled at the sit-down with the bank's developers
    (items 7 and 8).
- **Replaces:** ADR-0018 (pooled account, withdrawn and kept as a fallback).
- **Touches:**
  - ADR-0006 (statements become notifications plus a daily file);
  - ADR-0008 (first inbound endpoints);
  - ADR-0010 (one cross-tenant read).

## Context

- **Statements alone carry too little** (2026-10-03 samples): no
  transaction id, no payer phone, and narration truncated at about 34
  characters.
- **The collections service fills the gap.** The bank checks a payment's
  reference with WEPL before taking the money, then notifies WEPL of each
  payment.
- **One account per group means the account names the group.** Nothing has
  to be routed between groups.

## Decision

1. **Each group's account can have the service.** It is linked as an
   `ExternalAccount` with connector `business_connect`, like any custodian
   account.
2. **The reference is the member's own mobile number**, e.g. `0712597024`.
   - The member code (`M01`) also works.
   - No group code is needed: the account the money goes to already names
     the group.
   - A fund code may be added (`0712597024 WEL`) to pay into a fund other
     than the group's default (ADR-0023); the check refuses a code the group
     does not have.
   - Spaces, `+254` and `#` are ignored. A number inside other words is not
     read as a reference.
3. **A quoted number names the member paid for**, ahead of the payer's own
   number, so someone can pay for a member.
   - A quoted number that is not a current member's is held, never credited
     to the payer instead.
   - A member code still comes first (ADR-0012 rules for ended spells are
     unchanged).
4. **The bank's reference check** (`POST /collections/validate`) accepts a
   reference only if it names a current member of the group whose account
   it names. It returns the group's name, never a member's.
5. **A payment notification** (`POST /collections/notify`) goes to that
   group's ordinary `ingest`, inside its tenant. That covers:
   - duplicates and conflicts;
   - gaps in the bank's numbering;
   - attribution;
   - the running-balance check.

   A payment for an account WEPL does not know is refused, never parked.
6. **One cross-tenant read.** WEPL finds the account from its number in a
   declared, audited cross-tenant operation that reads only the account's id
   and tenant. Everything else runs inside the tenant.
7. **Every request is signed.**
   - The signature is HMAC-SHA256 over the timestamp and the body.
   - A request is accepted within 5 minutes of its timestamp.
   - The endpoints are off until `WEPL_COLLECTIONS_SECRET` (32+ characters)
     is set.
   - ASSUMPTION: the bank can sign requests. Mutual TLS or an IP allowlist
     may replace this.
8. **The request format is WEPL's placeholder** (`custody/api/payload.py`)
   until the bank's is known. An adapter will map the bank's format onto it.

## Alternatives

- **One pooled WEPL account (ADR-0018):** withdrawn. WEPL would hold client
  money, which needs a legal opinion, a client-money account and routing
  between groups.
- **Statements only:** keeps the gaps listed above.

## Consequences

- WEPL still never holds money and needs no client-money arrangement.
- Members must quote their registered number. A changed number must be
  updated in the group first, or the payment is held.
- Payouts are still made by the group's signatories at the bank. WEPL
  matches each one to its mandate (ADR-0006).

## Open, for the bank

- Does each chama account get its own collections setup, and which account
  number comes in the request?
- How long can a reference be, and is `#` accepted?
- Does the notification carry the payer's full phone number, or a masked
  one?
- If WEPL does not answer the check in time, does the bank accept the
  payment, refuse it, or queue it?
- Are notifications retried until acknowledged?
- Does the daily file use the same transaction ids, and does it number the
  account's transactions?
