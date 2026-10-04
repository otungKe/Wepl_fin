"""Types a connector (a custodian integration) implements or produces."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from contexts.shared_kernel.money import Money

from .domain.resolution import Outcome
from .domain.statement import BankLine, Connector, LineKind

__all__ = ["BankLine", "Connector", "CustodyError", "ExternalAccountView", "IngestResult", "LineKind", "Outcome",
           "ReconciliationView"]


class CustodyError(ValueError):
    pass


@dataclass(frozen=True)
class ExternalAccountView:
    id: int
    group_id: int
    fund_id: int
    institution: str
    account_number: str
    account_name: str
    connector: str
    currency: str
    closed_at: datetime | None = None

    @property
    def is_open(self) -> bool:
        return self.closed_at is None

    def __str__(self):
        return f"{self.institution} {self.account_number}"


@dataclass
class IngestResult:
    new: int = 0
    duplicates: int = 0
    conflicts: int = 0


@dataclass(frozen=True)
class ReconciliationView:
    id: int
    statement_balance: Decimal | None
    ledger_cash: Decimal
    difference: Decimal | None
    member_interests: Decimal
    unattributed: Decimal
    unexplained_out: Decimal
    retained: Decimal
    lines_seen: int
    lines_unresolved: int
    sequence_gaps: list
    balance_breaks: list
    open_alerts: int
    balanced: bool
    run_at: datetime | None = None

    @property
    def cash(self) -> Money:
        return Money(self.ledger_cash)
