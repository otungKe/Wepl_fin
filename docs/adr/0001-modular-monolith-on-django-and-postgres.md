# ADR-0001: Modular monolith on Django 5.2 LTS and PostgreSQL

- **Status:** Proposed (2026-09-30)
- **Decider:** Harry

## Context

The pilot must show I&M Bank that the platform is stable now and in future
"beyond reasonable doubt" (CONFIRMED: Harry, 2026-09-28). The team is small.
The first WEPL taught that Celery and Redis cost more than they gave, and that
the ledger (Python `Decimal`, PostgreSQL triggers) was the best part
(CONFIRMED: reverse-engineering report).

## Decision

- One deployable: a modular monolith of bounded contexts (ADR-0002).
- Python 3.12, Django 5.2 LTS, PostgreSQL 16, psycopg 3.
- Django sits at the edges: ORM, transactions, commands, and later HTTP.
  Business rules live in each context's pure `domain` package.
- Background work uses a PostgreSQL outbox, claimed with
  `SELECT … FOR UPDATE SKIP LOCKED`, delivered at least once, and run by
  management commands on a schedule. There is no Redis and no Celery.

## Alternatives considered

- **Django 6.0** (proposed on branch `claude/project-thread-sdt0p6`). Newer, but
  not a long-term-support release. 5.2 LTS is supported to April 2028, which
  matters to a bank's due diligence. **Open question for Harry:** 5.2 LTS or
  6.0. Nothing in this code depends on the difference.
- **Microservices.** Rejected by guideline 33 until a workload proves the need.
- **Celery and Redis.** Not needed until work cannot finish inside a request
  plus a scheduled sweep.

## Consequences

- One database to back up, restore and reason about; one process to operate.
- Contexts talk through in-process public surfaces, so a context can be
  extracted later without changing its callers' contracts.
- Scheduled work is visible: each run is a command with logs and a result.
