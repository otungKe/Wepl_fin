"""A fund's contribution rule, as the group writes it in its constitution
(ADR-0022). Every setting is the group's own; WEPL picks none (Harry,
2026-10-04: "All those should be a group decision"). A fund the
constitution gives no rule takes any amount at any time and has no arrears.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from contexts.shared_kernel.money import Money


class ContributionError(ValueError):
    pass


class Frequency(StrEnum):
    WEEKLY = "weekly"    # due_day is the weekday, 1 (Monday) to 7 (Sunday)
    MONTHLY = "monthly"  # due_day is the day of the month, 1 to 28


class PaymentOrder(StrEnum):
    OLDEST_FIRST = "oldest_first"    # a payment clears the oldest amount owed first
    CURRENT_FIRST = "current_first"  # ... the most recent amount owed first


class JoinersOweFrom(StrEnum):
    JOINING = "joining"  # from the first due date on or after the day they joined
    START = "start"      # back to the rule's starts_on


class ExtraPayments(StrEnum):
    PAY_AHEAD = "pay_ahead"  # paying more than is due covers later periods
    SAVINGS = "savings"      # it is savings only; later periods are still owed


class LeaverArrears(StrEnum):
    WRITTEN_OFF = "written_off"
    DEDUCTED_FROM_PAYOUT = "deducted_from_payout"


class FineKind(StrEnum):
    NONE = "none"
    FIXED = "fixed"      # ``value`` is an amount per late period
    PERCENT = "percent"  # ``value`` is a percentage of what is still owed for the period


@dataclass(frozen=True)
class LateFine:
    kind: FineKind
    value: Decimal = Decimal(0)
    grace_days: int = 0


@dataclass(frozen=True)
class ContributionRule:
    fund_id: int
    frequency: Frequency
    amount: Money
    due_day: int
    starts_on: date
    payment_order: PaymentOrder
    joiners_owe_from: JoinersOweFrom
    extra_payments: ExtraPayments
    late_fine: LateFine
    leaver_arrears: LeaverArrears

    @classmethod
    def parse(cls, raw: dict) -> ContributionRule:
        def need(name):
            if raw.get(name) in (None, ""):
                raise ContributionError(f"Each fund's contribution rule must state {name}.")
            return raw[name]
        try:
            frequency = Frequency(need("frequency"))
            due_day = int(need("due_day"))
            if not (1 <= due_day <= (7 if frequency is Frequency.WEEKLY else 28)):
                raise ContributionError("due_day is 1-7 (Monday-Sunday) for weekly, 1-28 for monthly.")
            amount = Money.of(need("amount"))
            if not amount.is_positive:
                raise ContributionError("A contribution amount must be more than zero.")
            return cls(fund_id=int(need("fund_id")), frequency=frequency, amount=amount, due_day=due_day,
                       starts_on=date.fromisoformat(need("starts_on")),
                       payment_order=PaymentOrder(need("payment_order")),
                       joiners_owe_from=JoinersOweFrom(need("joiners_owe_from")),
                       extra_payments=ExtraPayments(need("extra_payments")), late_fine=_fine(need("late_fine")),
                       leaver_arrears=LeaverArrears(need("leaver_arrears")))
        except ContributionError:
            raise
        except (ValueError, TypeError, InvalidOperation) as exc:
            raise ContributionError(f"Contribution rule: {exc}") from None

    def to_dict(self) -> dict:
        fine = {"kind": self.late_fine.kind.value}
        if self.late_fine.kind is not FineKind.NONE:
            fine |= {"value": str(self.late_fine.value), "grace_days": self.late_fine.grace_days}
        return {"fund_id": self.fund_id, "frequency": self.frequency.value, "amount": str(self.amount.amount),
                "due_day": self.due_day, "starts_on": self.starts_on.isoformat(),
                "payment_order": self.payment_order.value, "joiners_owe_from": self.joiners_owe_from.value,
                "extra_payments": self.extra_payments.value, "late_fine": fine,
                "leaver_arrears": self.leaver_arrears.value}


def _fine(raw) -> LateFine:
    if not isinstance(raw, dict):
        raise ContributionError("late_fine is {\"kind\": \"none\"}, or a kind with value and grace_days.")
    kind = FineKind(raw.get("kind"))
    if kind is FineKind.NONE:
        return LateFine(kind)
    if raw.get("value") in (None, "") or raw.get("grace_days") in (None, ""):
        raise ContributionError("A late fine must state its value and grace_days.")
    value, grace = Decimal(str(raw["value"])), int(raw["grace_days"])
    if value <= 0 or grace < 0 or (kind is FineKind.PERCENT and value > 100):
        raise ContributionError("A fine's value must be above zero (a percentage at most 100), grace_days 0 or more.")
    return LateFine(kind, value, grace)


def parse_contributions(raw) -> tuple[ContributionRule, ...]:
    rules = tuple(ContributionRule.parse(r) for r in (raw or []))
    funds = [r.fund_id for r in rules]
    if len(funds) != len(set(funds)):
        raise ContributionError("A fund has at most one contribution rule.")
    return rules
