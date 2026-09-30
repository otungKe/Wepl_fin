# The money core against the engineering guidelines

Audited 2026-09-30, against [engineering-guidelines.md](engineering-guidelines.md).
"First draft" is the first commit on this branch; "Now" is after the restructure.

**Key:** Meets · Partly · Not yet (the capability isn't built) · N/A

| # | Rule | First draft | Now |
|---|---|---|---|
| 1 | Domain before Django | Partly: flat Django apps | Meets: contexts chosen by capability (ADR-0002) |
| 2 | Bounded contexts | Partly: called "apps" | Meets |
| 3 | One owner per concept | Partly | Meets: ownership stated in each context's `__init__.py` |
| 4 | No cross-context DB coupling by convenience | **No**: connectivity imported governance and parties models | Meets: public surfaces only; FKs deliberate and listed (ADR-0004); enforced by test |
| 5 | Contexts independently understandable | Partly | Meets: docstring, public surface and tests per context |
| 6 | Standard internal structure | **No** | Meets: `domain/application/infrastructure/tests`, only where needed |
| 7 | Dependency direction; pure domain | **No**: rules mixed with ORM code | Meets for domain (enforced by test); shortcut for application recorded in ADR-0007 |
| 8 | Django at the edges | Partly | Meets |
| 9 | Rich domain model | **No**: dicts, Decimals, functions | Meets: `Money`, `Msisdn`, `JournalDraft`, `AccountKey`, `ConstitutionRules`, `FundBook` |
| 10 | Business rules have one home | Partly | Meets: each rule is in one domain module |
| 11 | API is an adapter | N/A: no HTTP API yet | N/A |
| 12 | Focused use cases, no god services | **No**: `connectivity/services.py` did everything | Meets: one module per use-case family |
| 13 | Domain / application / infrastructure split | **No** | Meets |
| 14 | No workflows in signals | Meets | Meets, enforced by test |
| 15 | Transactions match business boundaries | Partly | Meets: each `atomic` states its reason |
| 16 | Intentional events | Partly | Meets: outbox topics are business facts |
| 17 | Explicit workflows | Meets | Meets |
| 18 | Ledger integrity | Meets | Meets, with a fingerprint check on key reuse |
| 19 | Never delete financial history | Meets | Meets |
| 20 | Idempotency first-class | Partly: votes, proposals and notifications were not idempotent | Meets: repeated vote is a no-op, `request_key` on proposals, notification dedupe keys, outbox retry |
| 21 | Providers behind interfaces | Partly | Meets: `Connector` and `Notifier` ports; implementation chosen by settings |
| 22 | No provider language in the domain | Partly: `bank_txn_id` | Meets: `external_id`, provider detail in `metadata` |
| 23 | Tenancy is a security boundary | **No** | Partly: group isolation enforced and tested; tenancy model is an open question (ADR-0005) |
| 24 | Authorization is not authentication | Partly | Partly: business authorization is explicit for votes, cancellations and corrections (ADR-0008); authentication not built |
| 25 | Explicit security rules | Partly | Partly: approval, self-benefit, maker-checker and isolation rules are explicit and tested; boot guards refuse unsafe production settings; see the wepl-security skill |
| 26 | Reads and writes may differ | Meets | Meets: queries are separate from commands |
| 27 | Reports aren't the source of truth | Meets | Meets: reports derive from the journal |
| 28 | Backoffice is a product surface | Not yet | Not yet: officials' corrections are application commands the backoffice will call |
| 29 | Tests follow business boundaries | Partly | Meets: unit tests per domain, integration per context, cross-context suites |
| 30 | Test failure paths | Partly | Meets for money paths: duplicate, retry, invalid state, unauthorized actor, wrong group, provider failure, crash and reprocess. Not yet: cross-process concurrency, database failover |
| 31 | Observable | **No** | Partly: operation ids on audit, journal, outbox and reconciliation. Not yet: request ids, structured logs |
| 32 | Audit is not logging | Partly | Meets: deliberate audit records with group and operation |
| 33 | No premature microservices | Meets | Meets (ADR-0001) |
| 34 | Scaling follows workload | Meets | Meets |
| 35 | Repository structure | **No** | Meets: `backend/config`, `backend/contexts`, `docs/adr`, `docs/architecture` |
| 36 | Decisions documented | **No** ADRs | Meets: ADR-0001 to ADR-0007 |
| 37 | No utils/helpers | Meets | Meets, enforced by test |
| 38 | Domain naming | Partly: "connectivity", "parties" | Meets: custody, identity, communities, governance |
| 39 | No generic service layer | **No**: `services.py` in three apps | Meets, enforced by test |
| 40 | Small modules | Partly | Meets: 250-line limit enforced by test |
| 41 | No premature abstraction | Meets | Meets: no repository layer (ADR-0007) |
| 42 | Shortcuts are visible | Not stated | Meets: ADR-0007 |
| 43 | Explicit public surface | **No** | Meets: `public.py` and `contract.py`, enforced by test |
| 44 | Commands for state changes | Partly | Meets |
| 45 | Queries for reads | Partly | Meets |
| 46 | Explicit state machines | **No**: status strings set directly | Meets: proposal, mandate and line-correction transitions; invalid ones fail |
| 47 | Invariants at several layers | Meets | Meets (ADR-0003) |
| 48 | Concurrency considered | Partly | Partly: row locks, conditional updates, unique keys, SKIP LOCKED; not yet tested across processes |
| 49 | Background work safe to retry | Partly | Meets: ingestion, posting and delivery are idempotent |
| 50 | UX doesn't shape the domain | N/A | N/A |
| 51 | Deliberate API contracts | N/A | Partly: views returned across contexts are frozen dataclasses, not ORM rows |
| 52 | Schema is not the domain | Partly | Meets: domain types are separate from models |
| 53 | Performance keeps integrity | Meets | Meets |
| 54 | Integrity over convenience | Meets | Meets |
| 55 | Don't rebuild the old system blindly | Meets | Meets: only the ledger design was carried over, deliberately |
| 56 | Don't invent requirements | Partly | Meets: unknowns are marked in the ADRs (tenancy, Django version, I&M format, legal) |
| 57 | Evidence labels | Partly | Meets in the ADRs |
| 58 | ADRs for disagreements | **No** | Meets: Django 5.2 vs 6.0 recorded in ADR-0001 |
| 59 | Refactoring preserves behaviour | — | Meets: every earlier test was ported, and the demo output is unchanged |
| 60 | The golden rule | — | Each context states its concept, owner, invariants and contract |

## Behaviour changed on purpose during the restructure

- **Votes.** Repeating the same vote is now a no-op. Changing a vote is still
  refused.
- **Proposals.** They accept an optional `request_key`, so a retried
  submission returns the first proposal.
- **Journal keys.** Reusing a key for a different entry is now refused. Before,
  the second entry was silently dropped.
- **Notification retries.** A failing notification is tried at most once per
  delivery pass. Before, one pass could use up all of its attempts.
- **Phone numbers.** Validation is stricter: only Kenyan mobile numbers, with
  prefix 7 or 1, are accepted.
