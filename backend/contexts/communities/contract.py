from dataclasses import dataclass

from .domain.membership import MembershipStatus, Role, Segment

__all__ = ["FundView", "GroupView", "MembershipView", "MembershipStatus", "Role", "Segment"]


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
    role: str
    status: str
    code: str

    @property
    def is_active(self) -> bool:
        return self.status == MembershipStatus.ACTIVE

    @property
    def is_official(self) -> bool:
        return Role(self.role).is_official
