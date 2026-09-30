"""The states a proposal and a mandate move through. Anything else fails."""
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


PROPOSAL_TRANSITIONS = {
    ProposalStatus.OPEN: {ProposalStatus.APPROVED, ProposalStatus.REJECTED, ProposalStatus.CANCELLED},
}
MANDATE_TRANSITIONS = {
    MandateStatus.ISSUED: {MandateStatus.EXECUTED, MandateStatus.EXPIRED, MandateStatus.CANCELLED},
}


def ensure(transitions: dict, current, new) -> None:
    if new not in transitions.get(current, set()):
        raise InvalidTransition(f"Cannot move from {current} to {new}.")
