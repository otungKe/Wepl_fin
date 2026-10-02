"""A membership is the relationship between one person and one group: which
group, whether it is current, the member's code, and an optional title. It
owns nothing else (ADR-0012). What a member may do is a capability the group
grants in governance (ADR-0011); what they paid or are owed is the ledger's."""
from enum import StrEnum


class MembershipStatus(StrEnum):
    """ACTIVE, then LEFT, and never back. A person who returns gets a new
    membership with a new code, so the old code keeps meaning the old spell
    of membership."""

    ACTIVE = "active"
    LEFT = "left"


class MembershipError(ValueError):
    pass


def ensure_can_leave(status: str) -> None:
    if MembershipStatus(status) is not MembershipStatus.ACTIVE:
        raise MembershipError("This membership has already ended; a returning member joins again.")


TITLE_MAX = 60


def clean_title(title: str | None) -> str:
    """A group's own name for a member's responsibility ("Treasurer", "Pastor",
    "Coordinator"), or "" for none. It is a label and grants nothing (ADR-0011).
    "" is the only representation of no title: None and whitespace become "",
    and inner whitespace collapses to single spaces."""
    title = " ".join((title or "").split())
    if len(title) > TITLE_MAX:
        raise MembershipError(f"A title is at most {TITLE_MAX} characters.")
    return title


def member_code(sequence: int) -> str:
    """Format an allocated sequence number as a member code: M01, M02...

    The code is a stable business identifier: members quote it as the account
    reference on payments, and attribution matches on it. Allocation is not
    done here. The group hands out each sequence number once, under a row
    lock, and memberships are never deleted, so a code is never reused."""
    if sequence < 1:
        raise MembershipError("Member sequence starts at 1.")
    return f"M{sequence:02d}"
