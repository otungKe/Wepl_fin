"""A pooled collection account (ADR-0018): one bank account, many groups.

Every transaction on it belongs to exactly one group's fund, decided here
from what the payer or payout quoted, or to nobody yet, in which case it is
held. Nothing is ever routed to a guessed group."""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .statement import LineKind

PAYMENT_CODE_LENGTH = 5
_MEMBER_CODE = re.compile(r"M\d+")


@dataclass(frozen=True)
class PaymentReference:
    group_code: str
    member_code: str

    def __str__(self):
        return f"{self.group_code}-{self.member_code}"


def parse_reference(text: str) -> PaymentReference | None:
    """``K7QAP-M01``, ``k7qap m01`` and ``K7QAPM01`` all read the same:
    separators and case are ignored, because payers retype references."""
    compact = re.sub(r"[^A-Z0-9]", "", (text or "").upper())
    group, member = compact[:PAYMENT_CODE_LENGTH], compact[PAYMENT_CODE_LENGTH:]
    if len(group) < PAYMENT_CODE_LENGTH or not _MEMBER_CODE.fullmatch(member):
        return None
    return PaymentReference(group, member)


class RouteKind(StrEnum):
    BY_PAYMENT_CODE = "payment_code"  # a pay-in quoting group + member
    BY_MANDATE = "mandate"            # a payout quoting a mandate reference
    HOLD = "hold"                     # nobody yet: kept at platform level and alerted


@dataclass(frozen=True)
class Route:
    kind: RouteKind
    key: str = ""         # the payment code or the mandate reference
    member_code: str = ""
    reason: str = ""


def route(*, kind: LineKind, reference: str, quoted_mandates: tuple[str, ...]) -> Route:
    """Where a transaction on the pooled account belongs, from what it quotes."""
    if kind == LineKind.DEPOSIT:
        # Only the reference field counts: the bank validated it with WEPL
        # before taking the money. Codes found in free text would be a guess.
        ref = parse_reference(reference)
        if ref is None:
            return Route(RouteKind.HOLD, reason="The payment's reference is not a group payment code and member code.")
        return Route(RouteKind.BY_PAYMENT_CODE, key=ref.group_code, member_code=ref.member_code)
    if kind == LineKind.WITHDRAWAL:
        if len(set(quoted_mandates)) == 1:
            return Route(RouteKind.BY_MANDATE, key=quoted_mandates[0])
        why = "quotes no mandate reference" if not quoted_mandates else "quotes more than one mandate reference"
        return Route(RouteKind.HOLD, reason=f"Money left the collection account and {why}.")
    # Interest and charges on the pooled account belong to no single group.
    # Who bears or earns them is a financial rule not yet decided (ADR-0018).
    return Route(RouteKind.HOLD, reason=f"{LineKind(kind).value.capitalize()} on the collection account: "
                                        f"how it is shared between groups is not yet decided.")

