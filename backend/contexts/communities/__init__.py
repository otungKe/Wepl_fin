"""Communities context.

Owns: groups (chamas, welfare groups, collections), who belongs to them and in
what role, and the funds a group keeps.

Does not own: the group's rules and approvals (governance), what anyone is
owed (ledger), or where the money sits (custody).

A group is also, for now, the data-isolation boundary (ADR-0005).

Public surface: ``contexts.communities.public``.
"""
