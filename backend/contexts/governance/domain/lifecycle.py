"""The states a proposal, a mandate and a fund transfer move through.
Anything else fails."""
from enum import StrEnum


class InvalidTransition(ValueError):
    pass


class ProposalStatus(StrEnum):
    OPEN = "open"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class MandateStatus(StrEnum):
    ISSUED = "issued"
    EXECUTED = "executed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class TransferStatus(StrEnum):
    """A move between funds (ADR-0024): decided like a payout, then booked
    by custody, or failed if the money is no longer there to move."""

    OPEN = "open"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    BOOKED = "booked"
    FAILED = "failed"


PROPOSAL_TRANSITIONS = {
    ProposalStatus.OPEN: {ProposalStatus.APPROVED, ProposalStatus.REJECTED, ProposalStatus.CANCELLED},
}
MANDATE_TRANSITIONS = {
    MandateStatus.ISSUED: {MandateStatus.EXECUTED, MandateStatus.EXPIRED, MandateStatus.CANCELLED},
}


TRANSFER_TRANSITIONS = {
    TransferStatus.OPEN: {TransferStatus.APPROVED, TransferStatus.REJECTED, TransferStatus.CANCELLED},
    TransferStatus.APPROVED: {TransferStatus.BOOKED, TransferStatus.FAILED},
}


def ensure(transitions: dict, current, new) -> None:
    if new not in transitions.get(current, set()):
        raise InvalidTransition(f"Cannot move from {current} to {new}.")
