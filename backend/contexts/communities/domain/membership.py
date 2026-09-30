from enum import StrEnum


class Segment(StrEnum):
    SAVINGS = "savings"
    WELFARE = "welfare"
    COLLECTION = "collection"


class Role(StrEnum):
    CHAIR = "chair"
    TREASURER = "treasurer"
    SECRETARY = "secretary"
    MEMBER = "member"

    @property
    def is_official(self) -> bool:
        return self in (Role.CHAIR, Role.TREASURER, Role.SECRETARY)


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    LEFT = "left"


def member_code(sequence: int) -> str:
    """Members are numbered M01, M02... in joining order. Codes are never
    reused, so a code quoted on an old payment always means the same member."""
    if sequence < 1:
        raise ValueError("Member sequence starts at 1.")
    return f"M{sequence:02d}"
