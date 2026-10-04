"""Operators context (ADR-0021).

Owns: who WEPL's staff are and how they prove it: operator accounts
(provisioned, never self-registered), passwords, authenticator enrolment,
staged sign-in, server-side operator sessions with idle and absolute
limits, lockout after failed attempts, step-up for sensitive actions, and
which operator capabilities each operator role carries.

Does not own: members or their capabilities in a group (communities,
governance), what an operator may see or do inside a context (each context
still refuses for itself), or the audit trail of what an operator does in a
group (audit, with the actor ``operator:<id>``).

Public surface: ``contexts.operators.public``.
"""
