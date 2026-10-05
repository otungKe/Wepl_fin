from dataclasses import dataclass
from datetime import date

from .domain.standing import Standing

__all__ = ["ContributionsError", "MemberStanding", "Standing"]


class ContributionsError(Exception):
    pass


@dataclass(frozen=True)
class MemberStanding:
    membership_id: int
    code: str
    name: str
    active: bool
    fund_id: int
    as_of: date
    standing: Standing
