"""A group's constitution, as rules the software applies."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from contexts.shared_kernel.money import Money


class RulesError(ValueError):
    pass


class ApproverSet(StrEnum):
    OFFICIALS = "officials"
    MEMBERS = "members"


class SharingRule(StrEnum):
    PRO_RATA = "pro_rata"   # shared by members in proportion to their balances
    RETAINED = "retained"   # kept at group level


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
                approvers = ApproverSet(rule.get("approvers"))
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
                       interest=SharingRule(raw.get("interest", "pro_rata")), mandate_valid_days=days)
        except ValueError as exc:
            raise RulesError(str(exc)) from None

    def to_dict(self) -> dict:
        return {
            "approvals": [{"up_to": str(t.up_to.amount) if t.up_to else None, "approvers": t.approvers.value,
                           "required": t.required} for t in self.tiers],
            "allow_self_approval": self.allow_self_approval, "bank_charges": self.bank_charges.value,
            "interest": self.interest.value, "mandate_valid_days": self.mandate_valid_days,
        }

    def tier_for(self, amount: Money) -> ApprovalTier:
        for tier in self.tiers:
            if tier.up_to is None or amount <= tier.up_to:
                return tier
        raise AssertionError("unreachable: the last tier has no limit")
