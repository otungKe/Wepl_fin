"""What a member is allowed to do, granted explicitly by their group
(ADR-0011). A title such as "Treasurer" confers none of these; a group that
wants its treasurer to approve payouts grants that treasurer APPROVE_PAYOUT.

Only capabilities an existing workflow checks are defined here. Add one when
a workflow needs it, never in anticipation."""
from enum import StrEnum


class Capability(StrEnum):
    APPROVE_PAYOUT = "approve_payout"    # counts toward approval tiers reserved for designated approvers
    CANCEL_PAYOUT = "cancel_payout"      # cancel an open payout request someone else made
    CORRECT_RECORDS = "correct_records"  # attribute a payment, explain an outflow, sign off opening balances


def current(changes) -> frozenset[Capability]:
    """Capabilities held after a member's grant/revoke history, oldest first,
    given as (capability, granted) pairs."""
    held: set[Capability] = set()
    for capability, granted in changes:
        (held.add if granted else held.discard)(Capability(capability))
    return frozenset(held)
