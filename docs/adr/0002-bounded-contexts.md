# ADR-0002: The contexts, their layers and their public surfaces

- **Status:** Proposed (2026-09-30)

## Context

The guidelines require contexts to be chosen for business capability, with
one owner per concept, a pure domain, and explicit public surfaces (rules 1–7
and 43). The first draft of this code used flat Django apps, called each
other's models directly, and kept rules in `services.py` files.

## Decision

`backend/contexts/`:

| Context | Owns | Does not own |
|---|---|---|
| `identity` | People and phone numbers | Roles in groups; authentication (later) |
| `communities` | Groups (each founds its own tenant, ADR-0013), memberships and titles, funds | Rules, approvals, balances, custody |
| `governance` | Constitutions, proposals, approvals, mandates | Moving money, balances, members |
| `ledger` | Accounts, journal entries, derived balances | Why money moved; who anyone is |
| `custody` | Custodian accounts, statement lines, how each was accounted for, alerts, reconciliation | The money, mandates, the journal |
| `notifications` | Messages decided on (outbox) and their delivery | Deciding what is worth saying |
| `audit` | Accountability records and operation ids | Operational logs |
| `shared_kernel` | `Money` | Any business rule |

Each context has, only where needed:

- `domain/`: pure Python rules, value objects and state machines.
- `application/`: use cases (commands) and queries. Each command owns its
  transaction.
- `infrastructure/`: Django app config, ORM models, migrations, providers and
  management commands.
- `contract.py`: pure types that other contexts may use, even from their domain.
- `public.py`: the only module other contexts may import.

`backend/simulators/custodian_bank` is not a context. It stands in for the custodian bank in
tests and demos, and no context imports it.

**Naming.** The money-holding context is called **custody**, not "payments".
In the pilot, WEPL moves no money; it watches a custodian (ADR-0006). A future
`payments` context would own payout submission under Model C.

**Contributions.** "Contributions" (goals, cycles, arrears) is a capability
the pilot tracks by hand. It is not built yet (UNKNOWN: its rules come from
the pilot).

## Alternatives considered

- **Governance inside communities.** Rejected. Group rules and approvals change
  for different reasons than membership does, and have their own invariants.
- **Repositories for everything.** Rejected for now; see ADR-0007.

## Consequences

`tests/test_architecture.py` fails the build when:
- a context imports another context's internals;
- a domain or contract module imports Django, the database or a provider;
- any context imports a simulator;
- a context lacks an ownership statement or a `public.py`;
- a `utils`, `helpers` or `services` module appears;
- a module grows past 250 lines;
- signals are used.
