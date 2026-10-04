# ADR-0018: One WEPL collection account at the custodian bank

- **Status:** Proposed (2026-10-03).
  - The *choice* is Harry's: one WEPL collection account rather than one per
    group, made on 2026-10-03.
  - The *details* wait on the sit-down with the bank's developers.
  - Accepted only on Harry's word.
- **Supersedes, in part:**
  - ADR-0006, Model A ("WEPL never holds money");
  - ADR-0006's open question about the statement format.
- **Touches:**
  - ADR-0003 (sub-ledgers);
  - ADR-0008 (first inbound endpoints);
  - ADR-0009 and ADR-0010 (one bank account serving many tenants).

## Context

- **The statement samples (2026-10-03) carry too little.** A plain account
  statement has:
  - no transaction id;
  - no payer phone on pay-ins;
  - a narration truncated at about 34 characters.

  Attribution from statements alone is unreliable.
- **The collections service (Business Connect) offers what is missing:**
  - reference pre-validation;
  - instant payment notifications;
  - an integration API.

  CONFIRMED on its public pages, for business accounts only. The bank
  promises integration with "almost all systems". A sit-down between the
  bank's developers and WEPL's will settle the mechanism (Harry,
  2026-10-03).
- **Harry chose one WEPL business account** for every group's collections.

## Decision

1. **One account, many sub-ledgers.**
   - A `CollectionAccount` is the WEPL-owned bank account. It is platform
     data, not a tenant: WEPL is not a tenant (ADR-0010).
   - Each group fund that collects through it has its own
     `ExternalAccount`, a *sub-account*, linked to the `CollectionAccount`.
   - The fund's books, statement lines, attribution, mandates and per-fund
     reconciliation are unchanged; one fund per group per collection
     account.
2. **The payment reference is the group's payment code, then the member's
   own mobile number** (Harry, 2026-10-04): `1234566 0712597024`.
   - **The code has a fixed length of 7 digits:** 6 random digits
     (100000–999999), then a Damm check digit.
     - It is unique, drawn by the database at founding, and never changes.
     - Harry suggested 5 to 10 digits. A variable length was rejected: with
       separators optional, `1234 0712597024` and `12340 712597024` are the
       same digits.
   - **The check digit** catches every single mistyped digit and every swap
     of two neighbouring digits. Such a code names no group, so the bank's
     reference check refuses it before it takes the money.
   - **Only digits count.** `#`, spaces and `+254` are ignored, because `#`
     may submit a USSD entry and payers retype references.
   - **The number names the person.** Their current spell in that group is
     the member paid for (ADR-0012). Each number belongs to one person.
   - **Both halves must agree.** A pay-in is held if its code's group has no
     current member with that number.
   - **Capacity:** 900,000 groups. Changing the length needs an ADR.
   - **Open with the bank:** the longest reference each channel accepts
     (this one is 17 digits), and whether the payer's phone arrives masked.
     On an STK push, WEPL starts the payment and can use a shorter
     reference of its own.
3. **Every bank transaction is recorded once, as platform data, then routed
   to exactly one tenant.**
   - `Collection` holds the bank's fact, append-only and unique by the
     bank's transaction id.
   - `CollectionRouting` holds the decision, append-only:
     - a pay-in is routed by its reference to the group's sub-account;
     - a payout is routed by the mandate reference it quotes (mandate
       references are unique across WEPL).
   - Routing then hands the line to that tenant's ordinary `ingest`, inside
     that tenant's own context.
   - Nothing is ever posted to a guessed group. A transaction that cannot be
     routed is **held** at platform level and alerted to WEPL operations. It
     is not put in any group's books. Interest and charges on the pooled
     account are held too: who bears them is a financial rule not yet
     decided (UNKNOWN; for Harry).
4. **Platform data is visible only in a declared cross-tenant operation.**
   - The new tables carry row-level security with a policy that admits
     only `wepl_cross_tenant()`.
   - Code acting for a group sees none of the pooled account, and a group
     never sees another group's payments.
5. **Reconciliation has two levels.**
   - **Per fund:** unchanged. The sub-account's lines are the routed
     transactions.
   - **Per collection account (new):**
     - the bank's latest running balance equals the sum of every
       sub-account's `custody_cash` plus the net of held transactions;
     - the bank's numbering shows no gap;
     - the running balance chains line by line.

     It is a cross-tenant operation, recorded in `PoolReconciliationRun`
     and alerted to operations when off.
6. **Reference validation is a read-only question:** "does this reference
   name an active member of a group that collects here?". It answers accept
   or refuse, plus the group's name for the payer to confirm. It never
   returns a member's name or phone.
7. **Inbound endpoints** (`/collections/validate`, `/collections/notify`).
   These are WEPL's first public API.
   - Authenticated by an HMAC signature over the body with a timestamp,
     refusing replays older than 5 minutes.
   - The shared secret comes from settings, and the endpoints are off when
     it is unset.
   - Idempotent by the bank's transaction id.
   - The request format is WEPL's own placeholder. A bank adapter maps the
     real format once it is agreed.
   - ASSUMPTION: the bank supports a signature or mutual TLS; to be agreed
     at the sit-down.
8. **Payouts leave only against an issued mandate** of the owning group.
   They are submitted by WEPL operators under maker-checker for the pilot,
   and later by the bank's payment gateway. Built separately, after login
   exists for operators.

## Alternatives

- **One collection service per group account.** This keeps WEPL from
  holding money, but needs every chama to qualify as a business account and
  to be enrolled one by one. Not chosen.
- **Pooled money booked in one WEPL ledger, without sub-ledgers.** This
  would break per-group isolation and per-member claims. Rejected.

## Consequences

- **WEPL holds client money.** Before any real money:
  - a written legal opinion (UNKNOWN; INFERRED that a client-money or trust
    account, and possibly Central Bank of Kenya authorisation, are needed);
  - an account titled and kept apart from WEPL's own funds.
- **One account-level difference concerns every group on the account.**
  Per-fund `custody_cash` and the running-balance chain locate it.
- **The bank's validation call makes WEPL part of the payment path.** The
  bank's timeout behaviour is UNKNOWN.
- **Operators who can move money need login and maker-checker before the
  pilot.**
- **Open for the sit-down:** the questions in the Business Connect
  assessment (reference check timing, notification fields and retries,
  end-of-day file, reference format, payouts, the client-money account,
  sandbox).
