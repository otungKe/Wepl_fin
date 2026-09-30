from enum import StrEnum


class Segment(StrEnum):
    SAVINGS = "savings"
    WELFARE = "welfare"
    COLLECTION = "collection"


class MembershipStatus(StrEnum):
    """Membership is the only fact this context models about a person in a
    group. A title ("Treasurer", "Pastor", "Coordinator") is an optional label
    the group chooses; it grants nothing. What a member may do is a capability
    the group grants in governance (ADR-0011)."""

    ACTIVE = "active"
    LEFT = "left"


TITLE_MAX = 60


def clean_title(title: str | None) -> str:
    """A group's own name for a member's responsibility, or "" for none."""
    title = " ".join((title or "").split())
    if len(title) > TITLE_MAX:
        raise ValueError(f"A title is at most {TITLE_MAX} characters.")
    return title


def member_code(sequence: int) -> str:
    """Members are numbered M01, M02... in joining order. Codes are never
    reused, so a code quoted on an old payment always means the same member."""
    if sequence < 1:
        raise ValueError("Member sequence starts at 1.")
    return f"M{sequence:02d}"
