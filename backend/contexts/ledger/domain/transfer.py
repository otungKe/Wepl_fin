"""Money moved between two funds of one group (ADR-0024).

An entry stays inside one fund, so a move is two entries: one takes the
money out of the source fund's books, the other puts it into the
destination's. They are posted together and mirror each other line for
line: the same owners, the same amounts, and the cash leaves and arrives at
the same bank account. Nobody's money changes; only the fund it is in."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .accounts import AccountPurpose, Side
from .journal import JournalDraft, LedgerError

TRANSFER_OUT = "fund_transfer_out"
TRANSFER_IN = "fund_transfer_in"
TRANSFER_KINDS = frozenset({TRANSFER_OUT, TRANSFER_IN})
# Money is moved for its owners only: a member, or the group. Unattributed
# money has no known owner yet, and unexplained outflows are not money.
_OWNERS = frozenset({AccountPurpose.MEMBER_INTEREST, AccountPurpose.RETAINED})


def _shape(draft: JournalDraft, *, flip: bool) -> Counter:
    return Counter((p.account.purpose, p.account.member_id, p.account.external_account_id, p.account.currency,
                    p.side.opposite if flip else p.side, p.amount.amount) for p in draft.postings)


@dataclass(frozen=True)
class FundTransfer:
    """The pair of entries. Constructing one proves they are a valid move."""

    out: JournalDraft
    into: JournalDraft

    def __post_init__(self):
        o, i = self.out, self.into
        if (o.kind, i.kind) != (TRANSFER_OUT, TRANSFER_IN):
            raise LedgerError(f"A fund transfer is a {TRANSFER_OUT} entry and a {TRANSFER_IN} entry.")
        if o.group_id != i.group_id:
            raise LedgerError("Money moves only between funds of the same group.")
        if o.fund_id == i.fund_id:
            raise LedgerError("A fund transfer needs two different funds.")
        if (o.cause_type, o.cause_id) != (i.cause_type, i.cause_id):
            raise LedgerError("Both entries of a fund transfer share its cause.")
        if o.reverses_entry_id is not None or i.reverses_entry_id is not None:
            raise LedgerError("A fund transfer reverses nothing.")
        cash = [p for p in o.postings if p.account.purpose is AccountPurpose.CUSTODY_CASH]
        if len(cash) != 1 or cash[0].side is not Side.CREDIT:
            raise LedgerError("The money leaves the source fund's cash at one bank account.")
        owners = [p for p in o.postings if p is not cash[0]]
        if any(p.account.purpose not in _OWNERS or p.side is not Side.DEBIT for p in owners):
            raise LedgerError("Only a member's or the group's own money can move between funds.")
        if _shape(o, flip=True) != _shape(i, flip=False):
            raise LedgerError("The destination must receive exactly what the source gives: same owners, "
                              "same amounts, same bank account.")
