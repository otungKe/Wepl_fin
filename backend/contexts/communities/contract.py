from dataclasses import dataclass

from .domain.fund import FundStatus
from .domain.membership import MembershipStatus

__all__ = ["CommunityError", "FundStatus", "FundView", "GroupView", "MembershipView", "MembershipStatus"]


class CommunityError(ValueError):
    pass


@dataclass(frozen=True)
class GroupView:
    id: int
    tenant_id: int  # the group's own tenant identity: the group is the tenant (ADR-0010)
    name: str
    payment_code: str = ""  # quoted before the member code on pooled collections (ADR-0018)


@dataclass(frozen=True)
class FundView:
    id: int
    group_id: int
    name: str
    currency: str
    status: str

    @property
    def is_open(self) -> bool:
        return self.status == FundStatus.OPEN


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
