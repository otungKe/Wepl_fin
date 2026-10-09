"""Locks for rows the application may not lock itself.

Constitutions are append-only, so the application's role has no UPDATE on
them, and PostgreSQL requires UPDATE for SELECT … FOR UPDATE (ADR-0027).
A transaction-scoped advisory lock serialises adoptions per group instead;
the unique (group, version) constraint still refuses a duplicate version."""
from django.db import connection


def lock_constitution(group_id: int) -> None:
    """Hold, until the transaction ends, the right to adopt a version of this
    group's constitution."""
    with connection.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended('governance.constitution', %s))", [group_id])
