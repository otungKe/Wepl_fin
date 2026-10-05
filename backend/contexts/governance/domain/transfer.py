"""Whose money a move between funds takes (ADR-0024). The destination fund
always credits the same owners the same amounts: a transfer changes which
fund holds the money, never who owns it."""
from enum import StrEnum


class TransferFrom(StrEnum):
    PRO_RATA = "pro_rata"  # the members who share a pro-rata payout, by their balances
    MEMBER = "member"      # one member's own balance
    RETAINED = "retained"  # the group's own money in the fund


def shortfall(amount, *, owners_hold, cash, committed) -> str | None:
    """Why ``amount`` cannot move out of a fund, or None if it can. Money is
    all ``Money``: what the chosen owners hold there, the fund's cash at the
    bank, and what is already promised out of it (issued mandates, approved
    transfers not yet booked). Unattributed money is never in
    ``owners_hold``: its owner is not known yet."""
    if owners_hold < amount:
        return f"the chosen owners hold only {owners_hold} in the fund"
    if cash - committed < amount:
        return f"the fund has only {cash - committed} not already promised to a payout or another transfer"
    return None
