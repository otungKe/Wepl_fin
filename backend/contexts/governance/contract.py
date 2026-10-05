"""Pure types other contexts may use, including in their domain code."""
from dataclasses import dataclass
from datetime import datetime

from contexts.shared_kernel.money import Money

from .domain.capabilities import Capability
from .domain.contribution import (ContributionRule, ExtraPayments, FineKind, Frequency, JoinersOweFrom, LateFine,
                                  LeaverArrears, PaymentOrder, WaiverOf)
from .domain.lifecycle import InvalidTransition, MandateStatus, ProposalStatus
from .domain.mandate import MANDATE_REFERENCE, Allocation
from .domain.rules import (AccountReturns, ConstitutionRules, LeaverBalances, LeaverPayouts, LeaverRuleVersion, RulesError,
                           SharingRule)

__all__ = ["Allocation", "Capability", "ConstitutionRules", "GovernanceError", "InvalidTransition", "MANDATE_REFERENCE",
           "MandateStatus", "MandateView", "ProposalStatus", "ProposalView", "RulesError", "SharingRule",
           "AccountReturns", "LeaverBalances", "LeaverPayouts", "LeaverRuleVersion",
           "ContributionRule", "ExtraPayments", "FineKind", "Frequency", "JoinersOweFrom", "LateFine", "LeaverArrears",
           "PaymentOrder", "WaiverOf", "WaiverView"]


class GovernanceError(ValueError):
    pass


@dataclass(frozen=True)
class MandateView:
    id: int
    group_id: int
    fund_id: int
    reference: str
    amount: Money
    payee_name: str
    payee_account: str
    allocation: Allocation
    charged_member_id: int | None
    status: MandateStatus
    expires_at: datetime
    issued_at: datetime | None = None  # when the group's approval completed


@dataclass(frozen=True)
class ProposalView:
    id: int
    group_id: int
    fund_id: int
    amount: Money
    status: ProposalStatus
    required_approvals: int
    approvals: int
    mandate_reference: str | None


@dataclass(frozen=True)
class WaiverView:
    id: int
    group_id: int
    fund_id: int
    member_id: int
    owed: WaiverOf
    amount: Money
    status: ProposalStatus
    required_approvals: int
    approvals: int
    decided_at: datetime | None
