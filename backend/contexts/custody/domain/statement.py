"""What a custodian tells us, in custodian-neutral terms."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Iterable, Protocol


class LineKind(StrEnum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    INTEREST = "interest"
    CHARGE = "charge"
    OPENING = "opening"

    @property
    def is_inflow(self) -> bool:
        return self in (LineKind.DEPOSIT, LineKind.INTEREST, LineKind.OPENING)


@dataclass(frozen=True)
class BankLine:
    """One transaction as the custodian reported it. Provider-specific detail
    stays in ``metadata``."""

    external_id: str
    sequence: int
    posted_at: datetime
    kind: LineKind
    amount: Decimal
    narration: str = ""
    reference: str = ""
    counterparty_name: str = ""
    counterparty_msisdn: str = ""
    running_balance: Decimal | None = None
    metadata: dict = field(default_factory=dict)

    def same_fact_as(self, other_kind: str, other_amount: Decimal, other_sequence: int) -> bool:
        return (LineKind(other_kind), Decimal(other_amount), int(other_sequence)) == (
            LineKind(self.kind), Decimal(self.amount), int(self.sequence))


class Connector(Protocol):
    """How statements are fetched from a custodian."""

    def fetch(self, account_number: str) -> Iterable[BankLine]: ...
