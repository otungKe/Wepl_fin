"""The custodian connector port. Each bank or file format is an adapter that
turns the custodian's data into ``BankLine`` values; nothing else in WEPL
depends on a bank's API or file layout."""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Protocol


@dataclass(frozen=True)
class BankLine:
    bank_txn_id: str
    sequence: int
    posted_at: datetime
    kind: str  # deposit, withdrawal, interest, charge
    amount: Decimal  # always positive
    narration: str = ""
    reference: str = ""
    counterparty_name: str = ""
    counterparty_msisdn: str = ""
    running_balance: Decimal | None = None
    raw: dict = field(default_factory=dict)


class Connector(Protocol):
    def fetch(self, account_number: str) -> Iterable[BankLine]:
        """Return lines for the account. May return duplicates, lines out of
        order, or (for push-style feeds) miss lines that a later full
        statement sweep will supply. Ingestion copes with all three."""
