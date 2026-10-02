from __future__ import annotations

from dataclasses import dataclass

from contexts.shared_kernel.money import Money


@dataclass(frozen=True)
class Assessment:
    difference: Money | None
    gaps: tuple[int, ...]
    unresolved: int
    balanced: bool


def assess(*, statement_balance: Money | None, ledger_cash: Money, sequences: list[int],
           unresolved: int) -> Assessment:
    """Balanced means: WEPL's cash equals the custodian's latest running
    balance, no custodian sequence number is missing, and every line received
    has been accounted for."""
    gaps = tuple(sorted(set(range(min(sequences), max(sequences) + 1)) - set(sequences))) if sequences else ()
    difference = ledger_cash - statement_balance if statement_balance is not None else None
    balanced = (difference is None or difference.is_zero) and not gaps and unresolved == 0
    return Assessment(difference=difference, gaps=gaps, unresolved=unresolved, balanced=balanced)
