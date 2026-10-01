# Review: ledger infrastructure (`models.py`, `accounts.py`)

- **Date:** 2026-10-01.
- **Requested by:** Harry.
- **Code reviewed:** commit `a1f1b0a`.
- **What I read:**
  - the ledger domain (`accounts.py`, `journal.py`, `position.py`);
  - its application layer (`posting.py`, `queries.py`) and `public.py`;
  - migrations 0001–0004 and `persistence/{tenancy,postgres}.py`;
  - ADR-0003, ADR-0004 and ADR-0009;
  - the ledger's unit and integration tests, and `tests/test_tenancy.py`;
  - the only writer, custody's `bookkeeping.post_and_resolve`, and every
    reader.
- **Probes:** I ran them against PostgreSQL 16 as `wepl_app`, which
  row-level security binds:
  - each write ran in its own savepoint, inside a transaction that was
    rolled back afterwards;
  - deferred checks were forced to fire with `SET CONSTRAINTS ALL
    IMMEDIATE`, then set back to deferred.

  "Accepted" below means PostgreSQL would have let the write commit.
- **What these findings are about:** every hole found needs a raw write that
  bypasses `post_journal`. The application path never makes one. They
  matter because ADR-0003 promises that "no code path, shell session or
  future context can commit an unbalanced **or edited** ledger". Several
  probes break that promise.

## Status

Harry said "Yes to harden. Implement it" on 2026-10-01. Recommended changes
1–7 are in:
- migration `ledger 0005`;
- `infrastructure/accounts.py`, and the reversal race message in
  `application/posting.py`;
- tests:
  - `ledger/tests/integration/test_database_rules.py`, one per probe;
  - `tests/test_ledger_committed.py`, a real commit for P1.

Not done, as recommended: balance checkpoints (Important 8) and the
fingerprint serialisation (an Improvement).

**How the seal works:** each new entry's id is added to a
transaction-local list, `wepl.ledger_open_entries`. A transaction that posts
very many entries carries a long list. That is fine at pilot volume; revisit
it with checkpoints.

## Executive assessment

**The shape is right; the database enforcement is incomplete.**
- Accounts are opaque keys, created on first use.
- Entries and lines are append-only.
- Balances are always derived, and idempotency is per tenant.
- The deferred balance trigger is real.

But three things the design depends on are not held by PostgreSQL:
- **A committed entry can be extended.** New lines can be added to it later,
  as long as they balance among themselves.
- **A line's entry, its account and the line itself can sit in different
  tenants.** The balance check is evaluated under one tenant, so it cannot
  see accounts in another.
- **The account key's uniqueness spans tenants.** One tenant's row can block
  another tenant from ever opening its own account.

`accounts.resolve` also enforces fewer rules on its race path than on its
normal path.

**Verdict:** sound, but it needs significant hardening before it is the
financial record I&M is asked to rely on. It does not need a redesign.

## `models.py`

### Account

**Its identity is the domain's `AccountKey`** (CONFIRMED,
`domain/accounts.py`):
- `fund_id` and `purpose`;
- `member_id`, only for `member_interest`;
- `external_account_id`, only for `custody_cash`;
- `currency`.

**The unique constraint** `ledger_account_unique_key` on `(fund_id, purpose,
member_id, external_account_id, currency)` with `nulls_distinct=False`
mirrors the key exactly.
- `nulls_distinct=False` is required here: without it, two `retained`
  accounts with NULL member and NULL external account would both be allowed.
- Tested by `test_one_account_per_key_even_with_null_parts`. **Acceptable.**

**`group_id` is not part of the identity, and correctly so.**
- A fund belongs to one group (communities 0010), so the fund already
  implies the group.
- The ledger stores `group_id` so the domain can refuse a posting outside
  the entry's group and fund (`JournalDraft.__post_init__`).
- It is a *consistency* field, not an identity field.

**Two purpose rules are CHECK constraints in the database:**
- member interest ⇔ member;
- custody cash ⇔ external account.

**Four things are *not* checked by the database:**
1. **`normal_side` against `purpose`.** The domain derives it
   (`AccountPurpose.normal_side`), and ADR-0003 tabulates it. PostgreSQL
   accepted a `custody_cash` account with a **credit** normal side (probe
   P3).
   - Every balance query signs amounts by the account's stored
     `normal_side` (`_SIGNED`).
   - So such an account would report its cash with the wrong sign, forever:
     the table is append-only and cannot be corrected.
   - The domain defines the mapping; the infrastructure does not hold it.
2. **`purpose` values.** `choices` is Django-only. A raw insert of
   `purpose='anything'` is accepted, and every query would then silently
   ignore that account.
3. **`currency` values.** These are unchecked too. Communities now refuses
   anything but KES for funds (communities 0011), but the ledger takes its
   currency from the key, not from the fund.
4. **Tenant in the unique key.** The key does not include the tenant (probe
   P4, see Critical 3).

**Deletion and updates:** refused (`append_only`), and lines point at
accounts with `PROTECT`. So an account's identity and normal side are
immutable once written. **Correct.**

**Coupling to other contexts** (opaque numbers, no foreign keys; ADR-0004):
- `fund_id` and `group_id` are communities';
- `member_id` is a communities membership (a spell, ADR-0012);
- `external_account_id` is custody's.

They are opaque references, and that is appropriate: the ledger never
dereferences them. The purposes themselves are a custody-shaped chart of
accounts (cash at a custodian, unattributed in, unexplained out). That is
fine while custody is the only writer.
- Future products (loans, contributions receivable, interest accrual) will
  need new purposes. Each one is a new enum value plus CHECK clauses: a
  migration, not a redesign. **Acceptable.**

### JournalEntry

| Aspect | Finding | Assessment |
|---|---|---|
| Idempotency | `UNIQUE (tenant, idempotency_key)`. `post_journal` looks the key up first and, after a lost race, looks again and compares fingerprints. | Correct. Per tenant is right, since every caller works inside a tenant. |
| Fingerprint | Kind, cause and sorted `account | side | amount | currency` lines. A replay with different content is refused. | Correct. One caveat: it embeds `str(AccountKey)`, the dataclass repr. Renaming a key field changes every new fingerprint, and a retried old key would then be refused as "different". (Improvement) |
| Cause and operation | `cause_type`/`cause_id` are opaque, and indexed together. `operation_id` comes from audit's current operation. | Correct: an entry can be traced to the statement line and operation that caused it (`custody.line_trail`). |
| Reversal | `reverses` is a one-to-one, so PostgreSQL allows **one** reversal per entry. Whether it actually mirrors the original is checked only in the domain (`JournalDraft.reversal`). A raw "reversal" with arbitrary lines was accepted (P8), and so was one pointing at **another tenant's** entry (P6). | Important |
| Status | None. Corrections are new entries. | Correct: an entry is a fact, not a workflow. |
| Group and fund | Stored on the entry. Nothing in the database checks that its lines' accounts belong to that group and fund. An entry for fund B with lines on fund A's accounts was accepted (P7). The domain refuses it. | Important |
| Deletion | Refused (`append_only`). `reverses` and line foreign keys are `PROTECT`. | Correct |
| Indexes | `(fund_id, id)`, `(cause_type, cause_id)`, and the unique key. | Adequate for today's reads |

### JournalLine

| Aspect | Finding | Assessment |
|---|---|---|
| Amount | `numeric(18,2)`, with `CHECK amount > 0`. Two decimal places matches `Money` (`CENT`), and KES is the only currency allowed. | Acceptable while KES-only. A 0- or 3-decimal currency would need both `Money` and this column to change (ADR-required, as the fund review noted). |
| Side | `CHECK side IN ('D','C')` | Correct |
| Currency | Not stored on the line. It is the account's, and the domain refuses a posting whose `Money` currency differs from its account's. The balance trigger groups by account currency. | Correct, and better than a duplicated column |
| Relationships | `entry` and `account` foreign keys are `PROTECT`. Lines are append-only, so a line can never be detached or altered. | Correct |
| **Belonging to the entry** | **A new line can be inserted into an entry that committed earlier.** Append-only refuses UPDATE and DELETE, not INSERT. The balance trigger re-checks only that the whole entry still balances. Two balanced lines added to a posted entry were accepted (P1). | **Critical 1** |
| Tenant consistency | The line's tenant is stamped from context. Nothing ties it to its entry's or its account's tenant, because foreign-key checks ignore row-level security. See Critical 2. | **Critical 2** |
| Index | `(account, entry)` | Serves per-account sums |

## `accounts.py`

- **`_filter(key)`**
  - It maps the key to the five identity columns, exactly the unique key.
  - It leaves out `group_id`, which is correct: group is not identity (see
    Account).
  - It also leaves out the tenant. That is safe for reads, because
    row-level security scopes every query. It is not enough for the unique
    index (Critical 3).
- **`find(key)`**
  - It runs under row-level security, so it can only return the current
    tenant's account. **Safe.**
  - Without a tenant context it returns nothing, and the next create is
    refused by RLS (probe P10: `ProgrammingError`). It never writes a row
    without a tenant. **Safe.**
- **`resolve(key)`**
  - **Normal path:** find, and refuse a found account whose `group_id`
    differs from the key's. Then create in a savepoint, so a lost race
    leaves the transaction usable.
  - **Race safety:** two transactions creating the same key conflict on the
    unique index. The loser blocks until the winner commits, gets a unique
    violation, then reads the winner's row (READ COMMITTED gives the new
    statement a fresh snapshot). This is race-safe for the same tenant.
  - **But:**
    1. **The race path skips the group check.** The account returned by
       the second `get()` is never compared with `key.group_id`. The two
       paths enforce different invariants. (Important)
    2. **It catches any `IntegrityError`, not just the unique key.** A
       CHECK violation, a NULL tenant, or a future trigger's refusal all
       become a second `get()`. That raises a misleading
       `Account.DoesNotExist` and hides the real cause. (Important)
    3. **A collision with another tenant's account** gets that same
       misleading `DoesNotExist`, and the account can then never be
       opened (Critical 3).
    4. **It reports a group mismatch by raising `IntegrityError` from
       Python.** That makes a domain refusal look like a database
       constraint, so callers cannot tell them apart. (Improvement)
  - **Placement:** it is persistence (get-or-create by unique key), and it
    holds no business rule beyond the group check. It belongs in
    infrastructure. **Acceptable.**

## Database enforcement: what PostgreSQL guarantees today

| Guarantee | Held by | Holds against a raw write? |
|---|---|---|
| Nothing is ever updated, deleted or truncated in accounts, entries or lines | `append_only` triggers | **Yes** |
| Every entry has at least 2 lines and balances per currency, at commit | deferred constraint triggers (0002), evaluated under the entry's or line's tenant (0003) | **Yes, but only for lines and accounts visible under that tenant** (P2, P5) |
| A posted entry's lines are final | — | **No** (P1) |
| Amount > 0, side D or C | CHECK | Yes |
| One account per key | unique key | Yes, **but across all tenants** (P4) |
| Member and custody accounts carry their reference | CHECK | Yes |
| Normal side matches purpose | — | **No** (P3) |
| Purpose and currency are known values | — | **No** |
| A line, its entry and its account are in one tenant | — | **No** (P2, P5) |
| A line's account is in its entry's group and fund | — | **No** (P7) |
| One reversal per entry | one-to-one unique | Yes |
| A reversal mirrors its original and is in the same tenant | — | **No** (P6, P8) |
| An idempotency key is used once per tenant | unique | Yes |
| Rows land only in the current tenant | stamp trigger plus RLS `WITH CHECK` | Yes |

**The probes behind the "No" rows** (all accepted by PostgreSQL):
- **P1:** two balanced lines added to an already-posted entry. Its balances
  changed; its fingerprint did not.
- **P2:** an entry in tenant A whose two lines post to **tenant B's**
  accounts. The balance check joins lines to accounts under A, so B's
  accounts are invisible. Zero visible currencies are unbalanced, so it
  passes.
- **P5:** two tenant-A lines attached to **tenant B's** entry. Under A they
  balance. In any cross-tenant read (reconciliation, an I&M report), B's
  entry now has foreign lines.
- **P3:** a custody-cash account with a credit normal side.
- **P6:** a tenant-A entry recorded as reversing tenant B's entry. It also
  uses up B's entry's one allowed reversal.
- **P7:** an entry for fund B whose lines are on fund A's accounts.
- **P8:** a "reversal" whose lines do not mirror the original.
- **P4:** in tenant A, resolving an account with B's fund id **succeeded**.
  Tenant B then could not open its own account: `DoesNotExist`.

**Transactions and races:**
- `post_journal` puts the entry and its lines in one savepoint, and the
  balance check runs at the outer commit.
- Custody calls it inside its own transaction, together with the
  `LineResolution` and the audit write.
- Concurrent posts never lose updates, because nothing is a stored
  counter.
- Concurrent reversals of one entry with different keys both pass the
  application check. The one-to-one then refuses the second, but as a raw
  `IntegrityError` rather than "already reversed". It is safe, just
  unfriendly.

## Boundary assessment

**The ledger has no foreign key to and no import of another context.** Its
imports are only `shared_kernel.money`, `tenancy.contract` and
`audit.public`, and the architecture test holds this.
- Every external concept enters as an opaque number in an `AccountKey`, and
  the owning context's domain decides what to post (custody's
  `domain/accounting.py`).
- The infrastructure is not the source of any business rule except one: the
  group check in `resolve`, which is a consistency check.
- **Contributions and payments do not exist yet.** Nothing in these files
  assumes them.

**Two implicit cross-context assumptions:**
- that a fund id belongs to the current tenant (unchecked; Critical 3);
- that `member_id` is a membership spell. That is documented in ADR-0012,
  and harmless to the ledger.

## Critical findings

1. **Posted entries can be extended (P1).**
   - The domain defines an entry as one immutable fact: ADR-0003 says
     "never edits", and `load_draft` and the fingerprint describe it as
     posted.
   - The infrastructure allows inserting lines into any existing entry, so
     long as the entry still balances.
   - **Risk:** member balances, custody cash or retained money can change
     under an entry whose fingerprint, cause and audit trail still describe
     the original. That is exactly the "edited ledger" ADR-0003 says cannot
     be committed.
2. **A line's tenant is not tied to its entry's or its account's (P2, P5).**
   - The domain keeps every posting inside one group and fund, and ADR-0009
     makes the tenant the security boundary.
   - The infrastructure relies on stamping and row-level security, but
     foreign-key checks ignore row-level security. And the balance trigger,
     run under one tenant, cannot see the other tenant's rows.
   - **Risk:** one tenant's write can attach lines to another tenant's
     entries or accounts and still pass the balance check. Cross-tenant
     views (reconciliation, institution reporting, `cross_tenant`
     operations) then read a corrupted journal.
3. **The account key is unique across all tenants (P4).**
   - The domain treats a fund id as identifying one group's fund, so it
     assumes keys never collide between tenants.
   - The infrastructure enforces the key globally but reads it per tenant.
     So a row in tenant A with B's fund id is invisible to B, yet blocks B's
     insert. B's `resolve` then fails with `DoesNotExist` every time.
   - **Risk:** one tenant's mistaken or malicious posting permanently stops
     another group's money from being recorded.

All three need a write outside `post_journal`. Today only custody posts,
with ids that come from tenant-checked views. They are critical because the
ledger's own ADR says the database, not the callers, is the last line.

## Important findings

4. **`normal_side` can contradict `purpose` (P3).** Add a CHECK that
   encodes ADR-0003's table. Also add CHECKs on `purpose` and `currency`
   values.
5. **The database does not tie an entry's lines to the entry's group and
   fund (P7).** The domain refuses this; the database should too, because
   per-fund queries trust `account.fund_id` and entries are listed by
   `entry.fund_id`.
6. **Reversals are not checked by the database (P6, P8):** neither "same
   tenant" nor "mirrors its original". Today only the domain builds
   reversals, and only through `load_draft`.
7. **`resolve` enforces fewer invariants on its race path, and treats every
   `IntegrityError` as a lost race.**
8. **Balances are recomputed from every line on every read.**
   - `member_balances` and `fund_position` sum all of a fund's lines, and
     custody calls `member_balances` for each pro-rata event.
   - Cost grows with history, roughly quadratically across a fund's life.
     That is fine at pilot volumes (ASSUMPTION: tens of members, a few hundred statement lines a month per group).
   - It becomes the first scaling limit. The fix, when needed, is
     *derived* checkpoints (still never a stored running balance), and it
     is an ADR, not a patch now.

## Improvements

- Make the fingerprint independent of `AccountKey`'s repr: a stable,
  versioned serialisation.
- Raise `LedgerError` rather than a Python-made `IntegrityError` for a group
  mismatch in `resolve`.
- Translate a second, concurrent reversal into "already reversed".
- The tenant-aware balance trigger restores `app.tenant_id` only on its
  success path. On failure the transaction aborts anyway, so this is
  harmless; a comment would stop someone "fixing" it wrongly.

## Things that are already correct (keep them)

- Accounts are keyed, not configured. They are created on first use from
  the domain's `AccountKey`, and `group_id` is not in the identity.
- `nulls_distinct=False` on the account key.
- Lines carry no currency; it comes from the account, and the domain checks
  it.
- Entries, lines and accounts are append-only in PostgreSQL. `PROTECT`
  everywhere.
- The balance check is a **deferred** constraint trigger at commit, so lines
  can be written one by one, and it re-reads under the entry's own tenant.
- Idempotency is unique per tenant, with replay compared by fingerprint.
- Balances are derived, never stored. Positions come from one grouped query.
- No foreign key to or import of another context; external ids are opaque.
- `resolve`'s savepoint around the create.

## Recommended changes (evidence-backed)

**One migration (ledger 0005) and two small code changes.**

1. **Seal an entry at its own transaction.**
   - A line may only be inserted into an entry created in the same
     transaction.
   - Mechanism: the entry's insert trigger records its id in a
     transaction-local setting, and the line insert trigger requires its
     entry's id to be there.
   - `post_journal` always writes the entry and its lines together, so it
     is unaffected.
   - Closes Critical 1.
2. **Line consistency trigger** (`BEFORE INSERT ON ledger_journalline`):
   - read the entry and the account **under row-level security**, so a
     foreign one is invisible and refused;
   - require line, entry and account to have the same tenant;
   - require the account's `group_id` and `fund_id` to equal the entry's.

   Closes Critical 2 and Important 5.
3. **Entry insert trigger:** a `reverses` entry must be visible (same
   tenant). At commit, the deferred check also requires a reversal's lines
   to mirror the original's (same accounts and amounts, opposite sides).
   Closes Important 6.
4. **Put the tenant in the account key:** replace `ledger_account_unique_key`
   with `(tenant, fund_id, purpose, member_id, external_account_id,
   currency)`. Closes Critical 3.
   - It also helps to confirm, inside a tenant, that the fund id is the
     current tenant's. That check belongs at the caller (custody already
     reads the fund through a tenant-checked view). The ledger must not
     import communities.
5. **CHECKs on `ledger_account`:**
   - `normal_side` matches `purpose` (ADR-0003's table);
   - `purpose` is one of the five values;
   - `currency` is three capital letters.

   Closes Important 4.
6. **`resolve`:**
   - catch only the unique-key violation (by constraint name);
   - apply the group check to the account found after a lost race;
   - raise `LedgerError` for a group mismatch.

   Closes Important 7.
7. **Tests:** one per probe (P1–P8), each asserting refusal, plus a
   two-tenant collision test for `resolve`.

**Not recommended now:** balance checkpoints (Important 8). Raise them with
an ADR when volume says so.

## Do-not-change list

- Do not add `group_id` or the tenant to `AccountKey` or `_filter`'s identity
  semantics. The tenant belongs in the *unique index*; the key stays the
  domain's.
- Do not store balances or running totals on accounts.
- Do not add foreign keys from the ledger to communities or custody tables.
  Ids stay opaque (ADR-0004).
- Do not add a status to journal entries; correct by reversal.
- Do not make the balance trigger immediate. Deferral is what lets an entry
  be written line by line.
- Do not relax `append_only` for "maintenance"; there is no legitimate
  edit.
- Do not move the accounting decision (what to post) out of the calling
  context's domain into the ledger.

## Final verdict

**Fundamentally sound in design, but it needs significant hardening in
PostgreSQL before the ledger can carry the guarantee ADR-0003 already
claims.**
- The models, keys and append-only stance are right, and the application
  path uses them correctly.
- The gaps are all things the database should refuse and doesn't:
  - extending a posted entry;
  - mixing tenants across a line, its entry and its account;
  - a cross-tenant unique key;
  - unchecked normal sides, reversals, and group or fund consistency.

They are fixable with one migration and a small change to `resolve`. No
redesign is needed.
