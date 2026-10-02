"""Ledger context: the foundation of financial integrity.

Owns: accounts, journal entries and lines, and every balance derived from
them. Double-entry and append-only; corrections are reversals.

Does not own: why money moved (the context that decided the accounting
supplies a cause), or who groups, members and bank accounts are. It knows
them only as ids.

Invariants: every entry has at least two lines, balances per currency, has
positive amounts, and is never changed or deleted. These are enforced in the
domain (``JournalDraft``) and again by PostgreSQL (migration 0002).

Public surface: ``contexts.ledger.contract`` (pure types) and
``contexts.ledger.public`` (commands and queries).
"""
