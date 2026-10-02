# ADR-0001: Modular monolith on Django 5.2 LTS and PostgreSQL

- **Status:** Accepted for the Django version (Harry, 2026-09-30,
  [foundational decision 1](../architecture/foundational-decisions.md)); the rest Proposed
- **Decider:** Harry

## Context

The pilot must show I&M Bank that the platform is stable now and in future
"beyond reasonable doubt" (CONFIRMED: Harry, 2026-09-28). The team is small.
The first WEPL taught that Celery and Redis cost more than they gave, and that
the ledger (Python `Decimal`, PostgreSQL triggers) was the best part
(CONFIRMED: reverse-engineering report).

## Decision

- One deployable: a modular monolith of bounded contexts (ADR-0002).
- Python 3.12, Django 5.2 LTS at the latest patch (5.2.17 when written;
  `requirements.txt` sets that as the floor), PostgreSQL 16, psycopg 3.
- Django sits at the edges: ORM, transactions, commands, and later HTTP.
  Business rules live in each context's pure `domain` package.
- Background work uses a PostgreSQL outbox, claimed with
  `SELECT … FOR UPDATE SKIP LOCKED`, delivered at least once, and run by
  management commands on a schedule. There is no Redis and no Celery.

## Alternatives considered

- **Django 6.0** (proposed on branch `claude/project-thread-sdt0p6`). Rejected
  by Harry on 2026-09-30: 5.2 LTS is supported to April 2028, its ecosystem
  is mature, and upgrade pressure stays low while the architecture settles.
  A move to 6.x needs a named capability that 5.2 cannot provide acceptably,
  recorded in a new ADR. It never happens silently.
- **Microservices.** Rejected by guideline 33 until a workload proves the need.
- **Celery and Redis.** Not needed until work cannot finish inside a request
  plus a scheduled sweep.

## Consequences

- One database to back up, restore and reason about; one process to operate.
- Contexts talk through in-process public surfaces, so a context can be
  extracted later without changing its callers' contracts.
- Scheduled work is visible: each run is a command with logs and a result.
