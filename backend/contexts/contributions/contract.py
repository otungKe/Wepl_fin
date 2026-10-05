from dataclasses import dataclass
from datetime import date

from contexts.shared_kernel.money import Money

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
    fines_paid: Money = Money.zero()   # paid into the fund the group named for fines
    fines_beyond: Money = Money.zero()  # paid into it beyond every fine owed so far

    @property
    def fines_owed(self) -> Money:
        return self.standing.fines_total - self.fines_paid
