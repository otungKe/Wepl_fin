from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Side(StrEnum):
    DEBIT = "D"
    CREDIT = "C"

    @property
    def opposite(self) -> Side:
        return Side.CREDIT if self is Side.DEBIT else Side.DEBIT


class AccountPurpose(StrEnum):
    CUSTODY_CASH = "custody_cash"          # money held at the custodian for a fund
    MEMBER_INTEREST = "member_interest"    # one member's share of a fund
    UNATTRIBUTED_IN = "unattributed_in"    # received, not yet tied to a member
    UNEXPLAINED_OUT = "unexplained_out"    # left without an approved mandate
    RETAINED = "retained"                  # group-level money no single member owns

    @property
    def normal_side(self) -> Side:
        return Side.DEBIT if self in (AccountPurpose.CUSTODY_CASH, AccountPurpose.UNEXPLAINED_OUT) else Side.CREDIT


class AccountKeyError(ValueError):
    pass


@dataclass(frozen=True)
class AccountKey:
    """Identifies one ledger account. Accounts are created on first use."""

    group_id: int
    fund_id: int
    purpose: AccountPurpose
    member_id: int | None = None
    external_account_id: int | None = None
    currency: str = "KES"

    def __post_init__(self):
        object.__setattr__(self, "purpose", AccountPurpose(self.purpose))
        if (self.purpose is AccountPurpose.MEMBER_INTEREST) != (self.member_id is not None):
            raise AccountKeyError("Exactly the member-interest accounts carry a member.")
        if (self.purpose is AccountPurpose.CUSTODY_CASH) != (self.external_account_id is not None):
            raise AccountKeyError("Exactly the custody-cash accounts carry an external account.")
