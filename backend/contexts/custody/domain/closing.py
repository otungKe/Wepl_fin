"""When a custodian account may be closed (ADR-0015).

WEPL records that a fund's money is no longer held at an account only when
the custodian's own statement and WEPL's books both say nothing is left,
and nothing about the account is still in question.
"""
from __future__ import annotations

from contexts.shared_kernel.money import Money

from .reconciliation import Assessment


def closing_refusals(a: Assessment, *, statement_balance: Money | None, open_alerts: int) -> list[str]:
    """Why the account cannot close yet; empty when it can. An account the
    custodian never reported a line for holds nothing."""
    reasons = []
    if statement_balance is not None and not statement_balance.is_zero:
        reasons.append(f"the custodian still reports a balance of {statement_balance.amount}")
    if a.difference is not None and not a.difference.is_zero:
        reasons.append(f"WEPL's books differ from the statement by {a.difference.amount}")
    if a.gaps:
        reasons.append(f"statement lines are missing (sequence numbers {list(a.gaps[:5])})")
    if a.breaks:
        reasons.append(f"the running balance is broken at {list(a.breaks[:5])}")
    if a.unresolved:
        reasons.append(f"{a.unresolved} statement line(s) are not accounted for")
    if open_alerts:
        reasons.append(f"{open_alerts} alert(s) on its lines are still open")
    return reasons
