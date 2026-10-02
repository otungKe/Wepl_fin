"""Communities context.

Owns: groups (chamas, welfare groups, collections, and any other
independently governed group), who belongs to them (a membership: group,
status, a member code that is never reused, and an optional title; ADR-0012),
and the funds a group keeps.

Does not own: the group's rules, approvals and what each member is allowed
to do (governance: capabilities, ADR-0011), what anyone is
owed (ledger), or where the money sits (custody).

Each group is its own tenant (ADR-0010); row-level security keeps groups
apart, and this context's checks stay as defence in depth (ADR-0005).

Public surface: ``contexts.communities.public``.
"""
