---
name: wepl-testing
description: How to test Wepl_fin — real Postgres, where tests live per context,
  what TestCase does and does not prove here (deferred triggers DO fire at
  teardown), idempotency tests that can't pass for the wrong reason, failure
  paths, the property and architecture suites, and what CI gates. Use before
  adding or changing any test, or when a test fails and the fix is not obvious.
---

# Wepl_fin testing

Run from `backend/` with the repo's venv:

```bash
python manage.py test                                   # everything (~130 tests, ~30 s)
python manage.py test contexts.custody                  # one context
python manage.py test tests.test_architecture           # boundary rules
WEPL_PROPERTY_EXAMPLES=300 python manage.py test tests.test_properties
python manage.py makemigrations --check --dry-run       # CI fails on model drift
```

The tests need PostgreSQL 16. Triggers, row-level security,
`select_for_update`, partial unique constraints and `nulls_distinct` are
Postgres-only; never use sqlite. **Connect as `wepl_app`, never as
`postgres`.** A superuser ignores row-level security, so every tenancy test
would pass for the wrong reason; `tests/test_tenancy.py` fails first if you
try.

## Where tests go (guideline 29)

| Kind | Place | Base class |
|---|---|---|
| Domain rules (pure) | `contexts/<ctx>/tests/unit/` | `SimpleTestCase`, no DB |
| Use cases, DB rules | `contexts/<ctx>/tests/integration/` | `TestCase` |
| Cross-context: properties, isolation, architecture | `backend/tests/` | varies |

`backend/tests/scenario.py::Scenario` builds a group, members, a constitution
and a simulated I&M account **through public surfaces only**. Use it rather than
creating rows by hand.

**Tenant context in tests (ADR-0009).**
- **Each `Scenario` is its own tenant.** Pass `tenant_id=` to put a second
  group in the same tenant. Its helpers (`sync`, `approve`, `balance_of`,
  `assert_sound`) act inside it.
- **Direct calls and ORM reads need the context.** Wrap them in
  `with s.acting():`, or call `self.enterContext(s.acting())` at the end of
  `setUp`.
- **Tests without a scenario** use `act_for_new_tenant(self)`.
- **Build every scenario before entering a context.** Provisioning inside a
  tenant is refused.
- **Choose the layer you are testing.** Two groups in *one* tenant test the
  application checks (`tests/test_isolation.py`). Two tenants test row-level
  security (`tests/test_tenancy.py`).
- **Hypothesis runs many examples in one test method.** Use a `with` block per
  example, not `enterContext`, and fire deferred triggers *outside* the
  tenant block. `SET CONSTRAINTS` inside a released savepoint survives the
  outer rollback, so set it back to `DEFERRED`.

## What `TestCase` proves here (verified 2026-09-30)

- **Deferred balance trigger: it fires.** Django's `TestCase` teardown runs
  `SET CONSTRAINTS ALL IMMEDIATE` on Postgres, so every `TestCase` re-checks
  every journal it left behind. A probe test that created an entry with no
  lines failed at teardown with "at least 2 are required". To assert the
  trigger inside a test, call `SET CONSTRAINTS ALL IMMEDIATE` yourself, as
  `ledger/tests/integration/test_posting.py::check_deferred` does. (The
  original WEPL skill says the opposite; that was true of its setup, not this
  one.)
- **Immutability triggers: they fire immediately.** Wrap each expected failure
  in its own `transaction.atomic()` so it does not poison the test's
  transaction.
- **Not provable in a `TestCase`:**
  - real cross-connection concurrency (two workers, two connections);
  - `transaction.on_commit` callbacks, unless captured;
  - anything that commits.

  Use `TransactionTestCase` with threads for those. **Beware:** the
  append-only triggers reject TRUNCATE, so `TransactionTestCase`'s flush will
  fail on journal tables. A concurrency suite needs a teardown that drops and
  recreates the test database, or runs in a separate database.
- **Hypothesis.** Property tests use `hypothesis.extra.django.TestCase`, which
  rolls back per example.

## Idempotency tests must not pass for the wrong reason

In the original WEPL, a "replay is idempotent" test passed for years while the
service zeroed a holding and re-added one purchase. **Rule:** assert the
**accumulated** value across ≥ 2 distinct keys, *then* assert that replaying
one changes nothing. Where a use case writes both a journal and a domain row,
assert both after the replay.
`ledger/tests/integration/test_posting.py::test_distinct_keys_accumulate_and_a_replay_changes_nothing`
is the pattern.

## Failure paths (guideline 30)

For money workflows, cover:
- duplicate and replay;
- invalid transition (`InvalidTransition`, `InvalidCorrection`);
- unauthorized actor;
- **wrong group** (`tests/test_isolation.py`);
- provider failure (`notifications/tests/integration/test_outbox.py::Flaky`);
- crash and reprocess (`custody/tests/integration/test_faults.py`);
- faulty feed (`simulators.im_bank.connector.Faults`).

To prove a database rule, bypass the domain and write through the ORM or raw
SQL. Otherwise you are testing the guard above it, not the rule.

## What CI enforces (`.github/workflows/ci.yml`)

1. `makemigrations --check --dry-run`
2. The full suite, with `WEPL_PROPERTY_EXAMPLES=150`, which includes
   `tests/test_architecture.py`:
   - context boundaries;
   - a pure domain;
   - no simulator imports;
   - no `utils`/`helpers`/`services` modules;
   - a 250-line module cap;
   - no signals;
   - no mutable money counters;
   - every ADR indexed.
3. `migrate` and `demo_im_pilot` end to end.

There is no coverage gate, linter or type checker yet.

**Never get green** by adding `@skip`, loosening an architecture rule, or
raising the line cap without an ADR.

## Known gaps (2026-09-30)

- No cross-process concurrency suite: two `post_journal` calls on one key from
  two connections; two workers racing `execute_mandate`; two relays claiming
  one outbox row.
- No test against a real I&M statement format; the simulator stands in.
