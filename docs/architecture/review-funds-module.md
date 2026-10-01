# Review: the fund application module

- **Date:** 2026-09-30.
- **Requested by:** Harry, "Review the newly separated funds.py".
- **File:** `backend/contexts/communities/application/funds.py` at commit
  `450d30f`.
- **Evidence.** I read:
  - the `Fund` and `Group` models, and communities migrations 0001–0009;
  - `queries.py` and `contract.py`;
  - `audit`;
  - the tenancy SQL (`persistence/tenancy.py`);
  - the ledger models, account provisioning and journal domain;
  - custody and governance, which are the only other contexts that touch a
    fund;
  - the demo, `Scenario` and every test that opens a fund;
  - the constitution template (§2 accounts, §3 funds, §7 members);
  - the old WEPL report.

  I also ran a probe against PostgreSQL 16 as `wepl_app`, inside a
  transaction that was rolled back afterwards.
- **Status:** Harry said "Implement" on 2026-10-01. B1–B6 and tests 1–9 of
  section N are in: migration `communities 0010`, `domain/fund.py`,
  `funds.py`, `fund_view`, and tests in `communities/tests/{unit/test_fund,
  integration/test_funds}.py` and `tests/test_concurrency.py`. Still open:
  C1 (case of names), C5 (the default name), and D1–D3.
- **Not present:** there is no `contributions` or `payments` context yet
  (CONFIRMED, `backend/contexts/`; `overview.md`, "Not yet built").

## E. What exactly is a Fund? (answered first)

> **A fund is one of a group's named pools of money.** It has a name, a
> currency and an owning group. It is the unit that money is accounted,
> held and spent in. It holds no balance, rule or state of its own.

| Evidence | Class |
|---|---|
| The model has only `tenant`, `group`, `name`, `currency` and `created_at`. There is no balance, total, status, rule or payment field. | CONFIRMED |
| The constitution template §3 lists funds as rows of *name, purpose, contribution rule*, for example "Main savings" and "(optional) Welfare". It lists accounts separately (§2), and withdrawals are approved per group (§5). | CONFIRMED |
| Custody links a custodian account to a fund: "record where a fund's money is held" (`custody/application/accounts.py`). The ledger scopes every account and entry by `fund_id`. Governance proposes a withdrawal *from* a fund. | CONFIRMED |
| It is **not** a ledger account. The ledger has its own `Account` rows, created on demand when something is posted. | CONFIRMED |
| It is **not** a wallet, payment destination or custodian account. Those are custody's `ExternalAccount`. | CONFIRMED |
| Is it a contribution goal? Nothing in the code models a goal. §3's "purpose" and "contribution rule" columns suggest that a fund's *why* and *how members pay* sit next to it, in contributions, which is not built. | UNKNOWN (see I) |

**The name fits the evidence.** It is the constitution's own word, and it
means "pool", not "account". So Fund is genuinely a communities concept: the
group names its pools. The money, the custody of it and the rules for
spending it are owned elsewhere. STRONGLY INFERRED: CONFIRMED by the fields
and references, INFERRED as to where purpose and contribution rule will live.

## A. What is correct

| Claim | Evidence | Class |
|---|---|---|
| **It stays in its lane.** Opening a fund writes one `communities_fund` row and one audit event, and nothing else: no ledger account, journal entry, custodian account, contribution or payment. | code; probe | CONFIRMED |
| **No balance lives in communities.** Balances come only from `ledger.public` (`fund_position`, `member_balances`), computed from journal lines. | code | CONFIRMED |
| **A group may have no fund, or several.** `(group, name)` is unique in the database (`community_fund_name`, migration 0001), and nothing limits the count. The demo opens "Main savings"; a test opens two. | migration; `test_a_group_may_exist_without_a_fund_and_open_several` | CONFIRMED |
| **The ordinary path cannot reach another tenant's group.** `group_view` filters under RLS, so a foreign or unknown group, or a call with no tenant, gives "Unknown group" and nothing is written. | probe | CONFIRMED |
| **The fund and its audit event commit or roll back together.** `record` is a plain insert in the same outer transaction, so an audit failure leaves no fund. | probe: "fund after audit failure exists? False" | CONFIRMED |
| **The nested `atomic()` is needed** (see L). | Django semantics | CONFIRMED |
| **Other contexts reach funds only through the public surface.** `fund_view` is the only read; there are no model imports. Custody and governance keep deliberate, documented foreign keys to `communities.Fund`, with `PROTECT`. The ledger keeps a plain number. | `tests/test_architecture.py`; models | CONFIRMED |
| **Duplicate names are safe under concurrency.** The database constraint decides, not an `exists()` check. | migration | CONFIRMED by design; not tested concurrently |

## B. What must change

1. **The database does not tie a fund to its group's tenant (CONFIRMED
   by probe).** This is worse than the membership gap fixed in 0009:
   - Inside tenant A, a raw `Fund.objects.create(group_id=<B's group>)`
     **succeeded**. PostgreSQL's foreign-key check does not apply row-level
     security, and nothing else reads the group. The result is a fund in
     tenant A that belongs to B's group.
   - Under `cross_tenant`, a fund with `tenant = A`, `group = B` also
     succeeded.
   - `open_fund` never does this, because `group_view` stops it. But the
     rule "a fund lives in its group's tenant" is not held by the database,
     and custody and governance then trust `fund.group_id`.
   - **Fix:** a `BEFORE INSERT` trigger on `communities_fund`, the same
     check as membership 0009:
     - it reads the group **under RLS**, so a foreign group is invisible
       and refused;
     - it refuses a tenant other than the group's.
2. **A fund's group and currency can be changed (CONFIRMED: no trigger on
   `communities_fund` besides the tenant stamp).**
   - The ledger keys every account by `(fund_id, …, currency)`.
   - Custody copies the fund's currency onto the custodian account when it
     is linked.
   - If a fund's currency changes afterwards, its books read as empty in
     the new currency, while custody still posts in the old one.
   - If a fund's group changes, its proposals, mandates and books point at
     another group's fund.
   - **Fix:** PostgreSQL refuses changing `group` or `currency`, as it
     already does for a membership's group, person and code. Name changes
     and deletion are lifecycle questions (G, D2), not this fix.
3. **`IntegrityError` is reported as "already has a fund called X", whatever
   failed (CONFIRMED by probe).**
   - Under `cross_tenant` with no tenant, the tenant stamp is NULL, the
     `NOT NULL` fails, and the caller is told "FundProbeA already has a fund
     called 'Cross'", which is false.
   - After fix 1, the tenant-check trigger's refusals would be misreported
     the same way.
   - **Fix:**
     - call `require_tenant()` first, which removes the NULL case;
     - translate only a unique violation of **`community_fund_name`**
       (`exc.__cause__.diag.constraint_name`) into the duplicate-name
       message, and let every other integrity error propagate unchanged.
4. **`fund_view` raises `Fund.DoesNotExist` for an unknown or foreign fund
   (CONFIRMED by probe).**
   - Its siblings raise `CommunityError`, and governance and custody call it
     on user-supplied ids. An ORM exception crosses the context boundary.
   - **Fix:** `filter().first()` and `CommunityError("Unknown fund …")`,
     matching `group_view` and `membership`.
5. **Invalid names reach the database as raw errors (CONFIRMED by probe).**
   - `name=None` gives an `AttributeError`.
   - 81 characters gives `DataError: value too long`.
   - **Fix:** validate in a small domain function, as `clean_title` does:
     - `None` or blank → "A fund needs a name";
     - more than 80 characters → a `CommunityError`;
     - repeated spaces collapsed (`"Main   savings"` is stored as-is today).
6. **Currency is accepted unchecked (CONFIRMED by probe).**
   - `"kes"`, `"X1"` and `""` are stored, and `"USDX"` is a raw
     `DataError`.
   - `"kes"` would open ledger accounts in a "currency" that never matches
     `"KES"`.
   - **Fix now:** accept only a well-formed code (three upper-case letters).
     Which codes are *allowed* is D3.

## C. What needs investigation

1. **Case-insensitive names.** "Savings" and "savings" can both exist in one
   group (probe). Members name funds out loud, so two funds differing only
   by case would be confusing. INFERRED; there is no evidence either way.
   Making uniqueness case-insensitive needs a new unique index on
   `(group, lower(name))`. Your call.
2. **Who may open a fund.** No communities use case checks authorization,
   because in the pilot the operator does onboarding and there is no login or
   HTTP API yet (CONFIRMED, `overview.md`).
   - ADR-0011 adds a capability only with the workflow that needs it, so
     there is none for opening funds.
   - When groups manage themselves, opening a fund needs a governance
     capability, or a constitution change (§3 lists funds), decided then.
   - Tenant isolation is **not** authorization. Today only the tenant
     boundary applies.
3. **The ledger does not check that an entry's fund belongs to its group.**
   - `JournalEntry` has `group_id` and `fund_id` as plain numbers.
   - The domain checks that postings agree with the entry, not that the fund
     is the group's. Custody always builds both from one custodian account,
     so it holds today (INFERRED). It is a ledger question, not this
     module's.
4. **Deleting a group.** No database rule stops deleting a group that has no
   funds, members or other references yet, which leaves its tenant without
   a group. Outside this module; noted for the tenancy ADR follow-up.
5. **The default name `"Main fund"`.**
   - No code gives that name meaning. It only saves tests from passing a
     name; the demo passes "Main savings".
   - A pilot group's funds come from its constitution §3, so a silent
     default would name a real fund something the group never chose.
   - **Recommend** making `name` required, with tests passing one. It is a
     small change; say if you want it.

## D. ADRs required

1. **Tenant consistency of child rows.** Already raised in the membership
   review (C1). Fix B1 is the fund instance of it.
2. **Fund lifecycle.** Only *open* exists (G). Before any other step is
   built, decide:
   - whether a fund may be renamed. The audit keeps the old name, and
     history refers to the fund by id, so a rename does not break records.
   - whether a fund may be closed, and when: at zero balance only, with no
     pending mandates, and with its custodian account unlinked.
   - whether a closed fund can reopen;
   - that a fund is never deleted once anything refers to it. Today
     `PROTECT` foreign keys from custody and governance already stop that,
     but the ledger's plain `fund_id` does not.
3. **Currency.** Everything today assumes KES:
   - `Money` fixes two decimal places ("two places for KES");
   - ledger queries default to `"KES"`;
   - statement lines carry no currency and are read in the custodian
     account's currency;
   - the constitution template is in KES.

   A USD fund would *probably* work, because the ledger keeps currencies
   apart and never mixes them in a total. But nothing tests it, and a
   currency with other than two decimal places would be wrong. Decide:
   - KES only for the pilot (recommended: the evidence supports nothing
     else), or a named list;
   - whether one group may hold funds in different currencies;
   - that a fund's currency is fixed at opening (B2 makes it so).

## F. Context ownership

```text
Communities   Group, Membership, Fund
              └ names the pool, its group and its currency. No money, no rules.
Governance    Constitution (group-wide rules), Proposal/Mandate *from* a fund, Capabilities
              └ who may spend a fund's money, and on what terms.
Custody       ExternalAccount (fund ↔ custodian account), statements, matching, sharing
              └ where the fund's money physically is, and what moved.
Ledger        Account (keyed by fund_id + purpose [+ member | external account] + currency), JournalEntry/Line
              └ the only owner of balances.
Contributions (not built) cycles, arrears, goals; §3's "purpose" and "contribution rule" per fund
Payments      (not built) payouts through I&M's APIs
```

All CONFIRMED from the code, except the two contexts not yet built, which
come from `overview.md`.

The old WEPL did the opposite:
- its `contributions` app owned pools, welfare and shares funds;
- its ledger and M-Pesa models held foreign keys into them (report §2.8 and
  "Payments knows domain vocabulary").

The current split avoids that: no financial context holds a foreign key into
contributions, and the ledger holds none into communities.

## G. Fund lifecycle

```text
open_fund ──▶ OPEN        (the only state; no status field)
                │
                ├─ rename?      the database allows it; no use case    ─┐
                ├─ close?       no concept                              ├─ D2
                ├─ reopen?      no concept                              │
                └─ delete?      stopped once custody or governance      ─┘
                                refers to it (PROTECT); the ledger's
                                plain fund_id would not stop it
```

CONFIRMED. The unresolved question is D2. B2 closes the two changes
that would corrupt history today (group, currency); it does not decide
rename or close.

## H. Fund versus Ledger Account

**They are separate, joined by a deterministic key (CONFIRMED).**

- Communities never creates or knows about a ledger account.
- The ledger creates an account the first time a posting needs one
  (`ledger/infrastructure/accounts.py`, `resolve`: get or create by
  `(fund_id, purpose, member_id, external_account_id, currency)`, with the
  unique key settling races).
- One fund therefore has many ledger accounts: custody cash per custodian
  account, and one interest account per member. It has none until money is
  recorded.
- A `ledger_account_id` on `Fund` would be wrong: it would make one account
  stand for the fund, and give communities a view into the ledger.
- `open_fund` must not provision accounts. It correctly does not.

## I. Fund versus Contribution Goal

- **Distinct, as far as the evidence goes.**
  - A fund is where money is pooled and accounted.
  - The constitution attaches a *purpose* and a *contribution rule* to each
    fund (§3). "Amount per member per cycle" and penalties (§4) are about
    collecting, not pooling.
  - So contribution programmes will *refer to* a fund; they are not one.
    STRONGLY INFERRED.
- **A goal** ("school fees by December") is UNKNOWN. It could be a target
  inside a fund or a fund of its own. Decide when contributions is built,
  not now.
- **No duplicated concept exists today.** There is no wallet, pool, pot,
  campaign or goal model anywhere (CONFIRMED by grep). The only other
  "account" is custody's `ExternalAccount`, the real bank account, and the
  ledger's `Account`. Both are different things, correctly named.

## J. Tenant isolation

| Case | Result | Class |
|---|---|---|
| Own group | Fund opened in the current tenant | CONFIRMED |
| Foreign group id | RLS hides it, so "Unknown group", and nothing written | CONFIRMED (probe) |
| Unknown group id | "Unknown group" | CONFIRMED (probe, test) |
| No tenant | Every group is hidden, so "Unknown group". Safe, but it should be a tenancy error (B3). | CONFIRMED (probe) |
| Invalid tenant | `tenant(id)` refuses: "Unknown tenant" | CONFIRMED (tenancy test) |
| Superuser or staff | There is no such path: no admin, API or backoffice exists. Code runs as `wepl_app`, which RLS binds (`FORCE`). | CONFIRMED |
| Inside a declared cross-tenant operation | The group is visible, so `open_fund` proceeds, fails on the NULL tenant, and is misreported (B3). | CONFIRMED (probe) |
| **Raw insert naming a foreign group, inside a tenant** | **Accepted** (B1) | CONFIRMED (probe) |

**Where the final boundary is:**
- For reads, RLS is the final boundary.
- For writes, today it holds only *which tenant a row lands in*, not
  *whether its group is in that tenant*. B1 makes PostgreSQL enforce both.

## K. Currency

- **Who owns the rules?** Nobody yet (D3).
- **Is the API safe?** Only for `"KES"` today.
- **What the fund's currency drives:**
  - the custodian account's currency, copied when it is linked;
  - every ledger account opened for the fund;
  - the currency of withdrawal proposals (`Money.of(amount, fund.currency)`).
- **What stops mixing today:**
  - `Money` refuses to add different currencies;
  - a journal entry must balance per currency.

  So a USD fund cannot silently mix with KES, but it has never been
  exercised (UNKNOWN).
- **Recommendation:** accept only well-formed codes now (B6), and KES only
  until D3 says otherwise.

## L. Transaction + audit behavior

```text
@transaction.atomic                      ← one business operation
    group_view                          (read, under RLS)
    with atomic():  ← savepoint          only so a unique violation can be caught and turned into
        INSERT fund                      a CommunityError; without it the outer transaction is
                                         left broken and Django refuses further queries
    INSERT audit_event                   same outer transaction
return fund_view
```

- The fund and its audit event commit together, or neither does: CONFIRMED
  by probe (audit failure, then no fund).
- The savepoint is correct and stays. It is not decoration. Only its
  `except` is too broad (B3).
- `fund.opened` is an audit record, not a domain event. Nothing subscribes
  to it, and nothing should yet: no context needs to react to a fund being
  opened. The ledger and custody act when money moves or an account is
  linked.
- **What the audit keeps:**
  - actor, action and target (fund id);
  - `group_id`, and `tenant` (stamped);
  - `operation_id` (the current operation, set by `audit`);
  - `created_at`;
  - name and currency.

  That is enough to reconstruct the event (CONFIRMED, `AuditEvent` model).

## M. Database integrity

| Constraint on `communities_fund` | Can fail in `open_fund`? | Reported as |
|---|---|---|
| Unique `(group, name)`: `community_fund_name` | yes, the normal duplicate | "already has a fund called X", correct |
| `tenant_id NOT NULL` (the stamp gives NULL with no tenant) | yes, under `cross_tenant` | **"already has a fund", wrong** (B3) |
| FK `group_id → communities_group` | no: `group_view` just found it, and groups are `PROTECT`ed | would be misreported |
| FK `tenant_id → tenancy_tenant` | no: the stamp uses the current, existing tenant | would be misreported |
| RLS `WITH CHECK` | no: the stamped tenant is the current one | a `ProgrammingError`, not caught |
| `varchar(80)` name, `varchar(3)` currency | yes | a raw `DataError`, not caught (B5, B6) |
| Tenant-consistency trigger (after B1) | only on a bug | must not be misreported; B3 handles it |
| Group or currency immutable (after B2) | not on insert | — |

**Indexes:**
- The unique constraint gives `(group_id, name)`.
- The foreign keys give `group_id` and `tenant_id`.
- Other contexts look funds up by primary key.

That is sufficient (CONFIRMED).

## N. Tests required

Present:
- open several funds;
- duplicate name refused;
- `fund.opened` audited;
- unknown group;
- a group with no fund.

To add:
1. **Creation:**
   - name trimmed and repeated spaces collapsed;
   - blank or `None` name refused;
   - over 80 characters refused;
   - custom currency;
   - a malformed currency refused (B5, B6).
2. **Tenant:**
   - a foreign group refused, and nothing written;
   - no tenant gives `TenancyError`;
   - the database refuses a fund naming a foreign group inside a tenant,
     and a mismatched tenant under `cross_tenant` (B1).
3. **Uniqueness:**
   - the same name in two groups succeeds;
   - different names in one group succeed;
   - the case rule, whichever way C1 is decided.
4. **Integrity mapping:** a non-unique integrity failure is **not** reported
   as a duplicate name (B3).
5. **`fund_view`:** an unknown or foreign fund gives `CommunityError` (B4).
6. **Immutability:** PostgreSQL refuses changing a fund's group or currency
   (B2).
7. **Concurrency:** eight simultaneous opens of the same name give one fund
   and seven "already has"; eight different names give eight funds
   (`tests/test_concurrency.py`).
8. **Transaction:** an audit failure leaves no fund.
9. **Financial boundary:** opening a fund creates no ledger account,
   journal entry, custodian account or outbox message.

## O. Final verdict

**The module is correctly bounded and should stay as the dedicated fund
use case.**
- A fund is a communities concept: a group's named pool.
- Balances, custody, spending rules and contributions are already owned
  elsewhere, and nothing leaks back in.

**It is not ready as is.** The database must hold what the application
assumes:
- a fund lives in its group's tenant (B1);
- its group and currency never change (B2);
- errors must say what actually failed (B3–B6).

**Before anything beyond "open" is built, three decisions are needed:**
- the lifecycle (D2);
- currency (D3);
- the tenant-consistency ADR (D1).
