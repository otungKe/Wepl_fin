"""A group's constitution, as rules the software applies."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from contexts.shared_kernel.money import Money

from .contribution import ContributionRule, fines_funds, parse_contributions


class RulesError(ValueError):
    pass


class ApproverSet(StrEnum):
    DESIGNATED = "designated"  # only members the group granted APPROVE_PAYOUT (ADR-0011)
    MEMBERS = "members"        # any active member


# Constitutions adopted before ADR-0011 said "officials". They are append-only,
# so the old word is still read; migration governance 0004 granted every former
# official APPROVE_PAYOUT, so it means exactly what it meant then.
_FORMER = {"officials": ApproverSet.DESIGNATED}


class SharingRule(StrEnum):
    PRO_RATA = "pro_rata"   # shared by members in proportion to their balances
    RETAINED = "retained"   # kept at group level


class LeaverBalances(StrEnum):
    """What a former member's balance does after their spell ends, until it
    is paid out (ADR-0014). Each group chooses at onboarding."""
    SHARES_UNTIL_PAID = "shares_until_paid"   # keeps sharing interest and bank charges by balance
    FROZEN_AT_LEAVING = "frozen_at_leaving"   # takes part in no interest or charge dated after it left


class LeaverRuleVersion(StrEnum):
    """Which version of the leaver rules applies to someone who has already
    left, when the group adopts a new constitution (ADR-0014)."""
    AT_LEAVING = "at_leaving"  # the version in force on the day they left
    CURRENT = "current"        # the version in force on the day of each event


class LeaverPayouts(StrEnum):
    """Whether a former member bears a share of group spending paid out after
    they left (ADR-0014)."""
    NEVER = "never"
    APPROVED_BEFORE_LEAVING = "approved_before_leaving"  # only if the group approved it while they were a member
    ALWAYS = "always"


class AccountReturns(StrEnum):
    """How interest and charges on the group's one bank account are split
    among the funds it holds (ADR-0023). Inside each fund, ``interest`` and
    ``bank_charges`` then say who shares them."""
    DEFAULT_FUND = "default_fund"        # all of it to the group's default fund
    BY_FUND_BALANCE = "by_fund_balance"  # across funds by what each holds at the account


LEAVER_CHOICES = {"leaver_balances": LeaverBalances, "leaver_rule_version": LeaverRuleVersion,
                  "leaver_payouts": LeaverPayouts}
# The group's own choices, with no WEPL default: a constitution adopted from
# ADR-0014 (leavers) and ADR-0023 (funds sharing one account) on must state each.
REQUIRED_CHOICES = {**LEAVER_CHOICES, "account_returns": AccountReturns}


@dataclass(frozen=True)
class ApprovalTier:
    up_to: Money | None
    approvers: ApproverSet
    required: int


@dataclass(frozen=True)
class ConstitutionRules:
    tiers: tuple[ApprovalTier, ...]
    allow_self_approval: bool = False
    bank_charges: SharingRule = SharingRule.PRO_RATA
    interest: SharingRule = SharingRule.PRO_RATA
    mandate_valid_days: int = 14
    # None only in versions adopted before ADR-0014. They read as frozen,
    # because that is what the software did while they were in force.
    leaver_balances: LeaverBalances | None = None
    leaver_rule_version: LeaverRuleVersion | None = None
    leaver_payouts: LeaverPayouts | None = None
    # None only before ADR-0023: everything went to the account's one fund.
    account_returns: AccountReturns | None = None
    # Each fund's contribution rule (ADR-0022); a fund with none has no schedule.
    contributions: tuple[ContributionRule, ...] = ()

    def contribution_rule(self, fund_id: int) -> ContributionRule | None:
        return next((r for r in self.contributions if r.fund_id == fund_id), None)

    @property
    def fines_funds(self) -> set[int]:
        return fines_funds(self.contributions)

    @property
    def leaver_treatment(self) -> LeaverBalances:
        return self.leaver_balances or LeaverBalances.FROZEN_AT_LEAVING

    @property
    def leaver_version(self) -> LeaverRuleVersion:
        return self.leaver_rule_version or LeaverRuleVersion.AT_LEAVING

    @property
    def leaver_payout_share(self) -> LeaverPayouts:
        return self.leaver_payouts or LeaverPayouts.NEVER

    @property
    def account_split(self) -> AccountReturns:
        return self.account_returns or AccountReturns.DEFAULT_FUND

    def missing_choices(self) -> list[str]:
        return [name for name in REQUIRED_CHOICES if getattr(self, name) is None]

    @classmethod
    def parse(cls, raw: dict) -> ConstitutionRules:
        approvals = raw.get("approvals") or []
        if not approvals:
            raise RulesError("A constitution needs at least one approval rule.")
        tiers, last = [], None
        for i, rule in enumerate(approvals):
            up_to = rule.get("up_to")
            up_to = Money.of(up_to) if up_to is not None else None
            if up_to is None and i != len(approvals) - 1:
                raise RulesError("Only the last approval rule may have no upper limit.")
            if up_to is not None and last is not None and up_to <= last:
                raise RulesError("Approval rules must be in increasing order of amount.")
            last = up_to
            try:
                approvers = _FORMER.get(rule.get("approvers")) or ApproverSet(rule.get("approvers"))
            except ValueError:
                raise RulesError(f"approvers must be one of {[a.value for a in ApproverSet]}.") from None
            required = int(rule.get("required", 0))
            if required < 1:
                raise RulesError("Each approval rule needs at least one approval.")
            tiers.append(ApprovalTier(up_to, approvers, required))
        if tiers[-1].up_to is not None:
            raise RulesError("The last approval rule must have no upper limit.")
        days = int(raw.get("mandate_valid_days", 14))
        if not 1 <= days <= 90:
            raise RulesError("mandate_valid_days must be between 1 and 90.")
        try:
            return cls(tiers=tuple(tiers), allow_self_approval=bool(raw.get("allow_self_approval", False)),
                       bank_charges=SharingRule(raw.get("bank_charges", "pro_rata")),
                       interest=SharingRule(raw.get("interest", "pro_rata")), mandate_valid_days=days,
                       contributions=parse_contributions(raw.get("contributions")),
                       **{name: kind(raw[name]) if raw.get(name) else None for name, kind in REQUIRED_CHOICES.items()})
        except ValueError as exc:
            raise RulesError(str(exc)) from None

    def to_dict(self) -> dict:
        return {
            "approvals": [{"up_to": str(t.up_to.amount) if t.up_to else None, "approvers": t.approvers.value,
                           "required": t.required} for t in self.tiers],
            "allow_self_approval": self.allow_self_approval, "bank_charges": self.bank_charges.value,
            "interest": self.interest.value, "mandate_valid_days": self.mandate_valid_days,
            **{name: getattr(self, name).value for name in REQUIRED_CHOICES if getattr(self, name) is not None},
            **({"contributions": [r.to_dict() for r in self.contributions]} if self.contributions else {}),
        }

    def tier_for(self, amount: Money) -> ApprovalTier:
        for tier in self.tiers:
            if tier.up_to is None or amount <= tier.up_to:
                return tier
        raise AssertionError("unreachable: the last tier has no limit")
