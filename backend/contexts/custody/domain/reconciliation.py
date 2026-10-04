from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from contexts.shared_kernel.money import Money

from .statement import LineKind


@dataclass(frozen=True)
class Assessment:
    difference: Money | None
    gaps: tuple[int, ...]
    breaks: tuple[int, ...]
    unresolved: int
    balanced: bool


def balance_breaks(lines: Iterable[tuple[int, str, Decimal, Decimal | None]]) -> tuple[int, ...]:
    """The sequence numbers at which the custodian's running balance does not
    follow from the line before: previous balance, plus an inflow or minus an
    outflow, must equal the balance printed on the line.

    ``lines`` are (sequence, kind, amount, running_balance) in sequence order.
    The account starts at zero (an opening line carries any earlier balance).
    A line without a running balance is carried forward and checked at the
    next line that has one. A line left out breaks the chain at the next line
    received, even when the numbering shows no gap (a numbering derived from
    the statement has none). So do two missing lines that cancel out with a
    line between them, which the closing balance cannot show; two that cancel
    out back to back leave no trace in the balances at all."""
    expected, breaks = Decimal(0), []
    for sequence, kind, amount, running_balance in lines:
        expected += amount if LineKind(kind).is_inflow else -amount
        if running_balance is not None:
            if running_balance != expected:
                breaks.append(sequence)
            expected = running_balance  # one break is reported once, not on every later line
    return tuple(breaks)


def assess(*, statement_balance: Money | None, ledger_cash: Money, sequences: list[int],
           unresolved: int, breaks: tuple[int, ...] = ()) -> Assessment:
    """Balanced means: WEPL's cash equals the custodian's latest running
    balance, no custodian sequence number is missing, the running balance
    follows line by line, and every line received has been accounted for."""
    gaps = tuple(sorted(set(range(min(sequences), max(sequences) + 1)) - set(sequences))) if sequences else ()
    difference = ledger_cash - statement_balance if statement_balance is not None else None
    balanced = (difference is None or difference.is_zero) and not gaps and not breaks and unresolved == 0
    return Assessment(difference=difference, gaps=gaps, breaks=tuple(breaks), unresolved=unresolved,
                      balanced=balanced)
