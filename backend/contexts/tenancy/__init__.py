"""Tenancy context.

Owns: tenants and their lifecycle, the explicit tenant context every
operation on tenant-scoped data runs in, declared cross-tenant (system)
operations, and the PostgreSQL row-level security that enforces both
(foundational decisions 2–8, ADR-0009).

Does not own: any business rule. Communities own groups, the ledger owns
money, and so on. Each context classifies its own tables and keeps its own
application-level checks; tenancy is the database backstop underneath them.

Public surface: ``contexts.tenancy.public``.
"""
