"""A journal entry before it is posted, with the rules every entry obeys."""
from __future__ import annotations

from dataclasses import dataclass

from contexts.shared_kernel.money import Money

from .accounts import AccountKey, Side


class LedgerError(ValueError):
    pass


@dataclass(frozen=True)
class Posting:
    account: AccountKey
    side: Side
    amount: Money

    def __post_init__(self):
        object.__setattr__(self, "side", Side(self.side))
        if not isinstance(self.amount, Money):
            raise LedgerError("Posting amounts must be Money.")
        if not self.amount.is_positive:
            raise LedgerError(f"Posting amounts must be positive, got {self.amount}.")
        if self.amount.currency != self.account.currency:
            raise LedgerError("A posting's currency must match its account's currency.")


@dataclass(frozen=True)
class JournalDraft:
    """An entry ready to post. Constructing one proves it is valid."""

    idempotency_key: str
    group_id: int
    fund_id: int
    kind: str
    cause_type: str
    cause_id: str
    postings: tuple[Posting, ...]
    memo: str = ""
    reverses_entry_id: int | None = None

    def __post_init__(self):
        object.__setattr__(self, "postings", tuple(self.postings))
        object.__setattr__(self, "cause_id", str(self.cause_id))
        if not self.idempotency_key:
            raise LedgerError("Every entry needs an idempotency key.")
        if len(self.postings) < 2:
            raise LedgerError("An entry needs at least two postings.")
        totals: dict[str, Money] = {}
        for p in self.postings:
            if (p.account.fund_id, p.account.group_id) != (self.fund_id, self.group_id):
                raise LedgerError("Every posting must belong to the entry's group and fund.")
            signed = p.amount if p.side is Side.DEBIT else -p.amount
            totals[p.amount.currency] = totals.get(p.amount.currency, Money.zero(p.amount.currency)) + signed
        unbalanced = {c: str(t) for c, t in totals.items() if not t.is_zero}
        if unbalanced:
            raise LedgerError(f"Entry does not balance: {unbalanced}.")

    @classmethod
    def build(cls, *, postings, **fields) -> JournalDraft:
        """Like the constructor, but merges postings to the same account and
        side, and drops zero amounts, so callers can assemble lines freely."""
        merged: dict[tuple, Money] = {}
        for account, side, amount in postings:
            if amount.is_zero:
                continue
            k = (account, Side(side))
            merged[k] = amount if k not in merged else merged[k] + amount
        return cls(postings=tuple(Posting(a, s, m) for (a, s), m in merged.items()), **fields)

    def fingerprint(self) -> str:
        """What the entry says, independent of order: detects an idempotency
        key being reused for a different entry."""
        parts = sorted(f"{p.account}|{p.side}|{p.amount.amount}|{p.amount.currency}" for p in self.postings)
        return "\n".join([self.kind, self.cause_type, self.cause_id, *parts])

    def reversal(self, *, entry_id: int, idempotency_key: str, memo: str = "") -> JournalDraft:
        return JournalDraft(
            idempotency_key=idempotency_key, group_id=self.group_id, fund_id=self.fund_id, kind="reversal",
            cause_type="journal_entry", cause_id=str(entry_id), memo=memo or f"Reversal of entry {entry_id}",
            postings=tuple(Posting(p.account, p.side.opposite, p.amount) for p in self.postings),
            reverses_entry_id=entry_id)
