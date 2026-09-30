"""Communities context.

Owns: groups (chamas, welfare groups, collections), who belongs to them and in
what role, and the funds a group keeps.

Does not own: the group's rules and approvals (governance), what anyone is
owed (ledger), or where the money sits (custody).

Groups belong to a tenant; row-level security isolates tenants and this
context's checks keep groups apart within one (ADR-0005, ADR-0009).

Public surface: ``contexts.communities.public``.
"""
