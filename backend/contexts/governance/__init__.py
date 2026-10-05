"""Governance context.

Owns: each group's constitution (versioned rules), the capabilities the
group grants its members (what each may do, ADR-0011), withdrawal proposals,
the approvals members give, and the mandates that result. A mandate is the
group's authorisation for one payout; it can be executed once. Also the
group's decisions to move money between its funds (ADR-0024), which custody
books.

Does not own: moving money (the custodian does, under custody's watch), who
belongs to the group (communities), or balances (ledger).

Invariants: approvals follow the constitution in force when the proposal was
made; nobody approves a payout to themselves or their own request (unless
the constitution explicitly allows it); a proposal and a mandate only move
along their state machines; a mandate executes at most once.

Public surface: ``contexts.governance.contract`` and ``contexts.governance.public``.
"""
