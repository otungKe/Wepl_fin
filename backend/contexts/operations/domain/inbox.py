"""What an operator must look at, and in what order. Pure Python."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

# A reconciliation older than this means the nightly job missed the account.
STALE_AFTER = timedelta(hours=36)


class ItemKind(StrEnum):
    BOOKS_FAILED = "books_failed"                  # the ledger's integrity check failed
    UNMATCHED_OUTFLOW = "unmatched_outflow"        # money left without an approved mandate
    RECONCILIATION_DIFFERENCE = "recon_difference"
    STATEMENT_CONFLICT = "statement_conflict"
    NOT_RECONCILED = "not_reconciled"              # no recent reconciliation of an account

    @property
    def urgent(self) -> bool:
        """Urgent items are phoned through to the group's officials while SMS
        is on hold (Harry, 2026-09-28): money may be leaving or the books are
        wrong."""
        return self in (ItemKind.BOOKS_FAILED, ItemKind.UNMATCHED_OUTFLOW)


@dataclass(frozen=True)
class InboxItem:
    group_id: int
    group: str
    kind: ItemKind
    opened_at: datetime | None
    detail: str  # for the operator on the server; may name amounts, never sent by email

    @property
    def urgent(self) -> bool:
        return self.kind.urgent


def ordered(items: list[InboxItem]) -> list[InboxItem]:
    """Urgent first, then oldest first: the longer a problem sits, the worse."""
    return sorted(items, key=lambda i: (not i.urgent, i.opened_at.timestamp() if i.opened_at else float("-inf")))


def is_stale(last_run: datetime | None, now: datetime) -> bool:
    return last_run is None or now - last_run > STALE_AFTER
