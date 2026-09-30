from dataclasses import dataclass

from .domain.membership import MembershipStatus, Segment

__all__ = ["CommunityError", "FundView", "GroupView", "MembershipView", "MembershipStatus", "Segment"]


class CommunityError(ValueError):
    pass


@dataclass(frozen=True)
class GroupView:
    id: int
    name: str
    segment: str


@dataclass(frozen=True)
class FundView:
    id: int
    group_id: int
    name: str
    currency: str


@dataclass(frozen=True)
class MembershipView:
    id: int
    group_id: int
    person_id: int
    msisdn: str
    name: str
    title: str  # the group's own label, e.g. "Treasurer"; grants nothing (ADR-0011)
    status: str
    code: str

    @property
    def is_active(self) -> bool:
        return self.status == MembershipStatus.ACTIVE
