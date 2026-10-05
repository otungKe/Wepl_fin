"""Contributions context (ADR-0022).

Owns: what each member owes a fund under the group's own contribution rule
(when it is due, how payments clear it, arrears, paid-ahead amounts and late
fines), all derived on demand from the rule and the member's pay-ins.

Does not own: the rule itself (the constitution, governance), memberships
(communities), money (the ledger) or which pay-in belongs to whom (custody).
It stores nothing and posts nothing: a fine is shown as owed, never taken.

Public surface: ``contexts.contributions.public``.
"""
