"""Audit context.

Owns: the accountability record of business actions (who did what to which
thing, when, and as part of which operation), and the operation id that ties
one workflow's records together.

Does not own: operational logs (those are plain Python logging), or the
business state of anything it records.

Public surface: ``contexts.audit.public``.
"""
