"""Custody context.

Owns: the accounts where groups' money is actually held (in the pilot, each
group's own Chama Account at the custodian bank), the statement lines the custodian reports,
how each line was accounted for, alerts, and reconciliation of WEPL's books
against the custodian.

Does not own: the money (the group and custodian do), mandates (governance),
the journal (ledger), or members (communities). It decides the accounting for
each bank fact, and for each move between funds the group approved
(ADR-0024), and asks the ledger to post it.

Invariants: each custodian transaction is processed exactly once; every
outflow is matched to a mandate or raises an alert to every member; the books
equal the custodian's balance, or a reconciliation alert says why not.

Public surface: ``contexts.custody.contract`` (for connectors) and
``contexts.custody.public``.
"""
