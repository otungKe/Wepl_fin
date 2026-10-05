"""The accounting decision for each thing that happens at the custodian.

Business event -> accounting decision (here) -> journal (ledger). Each
function returns a ``JournalDraft``; the ledger checks it and posts it.
"""
from __future__ import annotations

from dataclasses import dataclass

from contexts.governance.contract import Allocation, SharingRule
from contexts.ledger.contract import (TRANSFER_IN, TRANSFER_OUT, AccountKey, AccountPurpose, FundTransfer, JournalDraft,
                                     Side)
from contexts.shared_kernel.money import Money

D, C = Side.DEBIT, Side.CREDIT


class AccountingError(ValueError):
    pass


@dataclass(frozen=True)
class FundBook:
    """The ledger accounts of one fund held at one custodian account. Several
    of a group's funds may be held at its one account (ADR-0023): each has
    its own cash there, and the account's balance is their sum."""

    group_id: int
    fund_id: int
    external_account_id: int
    currency: str = "KES"

    def _key(self, purpose, **kw) -> AccountKey:
        return AccountKey(group_id=self.group_id, fund_id=self.fund_id, purpose=purpose, currency=self.currency, **kw)

    def cash(self) -> AccountKey:
        return self._key(AccountPurpose.CUSTODY_CASH, external_account_id=self.external_account_id)

    def member(self, member_id: int) -> AccountKey:
        return self._key(AccountPurpose.MEMBER_INTEREST, member_id=member_id)

    def unattributed(self) -> AccountKey:
        return self._key(AccountPurpose.UNATTRIBUTED_IN)

    def unexplained(self) -> AccountKey:
        return self._key(AccountPurpose.UNEXPLAINED_OUT)

    def retained(self) -> AccountKey:
        return self._key(AccountPurpose.RETAINED)

    def draft(self, key: str, kind: str, cause_id, postings, memo: str = "",
              cause_type: str = "custody.statement_line") -> JournalDraft:
        return JournalDraft.build(idempotency_key=key, group_id=self.group_id, fund_id=self.fund_id, kind=kind,
                                  cause_type=cause_type, cause_id=str(cause_id), postings=postings, memo=memo)


def share_pro_rata(amount: Money, member_ids: list[int], balances: dict[int, Money]) -> dict[int, Money]:
    """Split by members' current balances; equally if nobody holds anything."""
    if not member_ids:
        raise AccountingError("The group has no active members to share this among.")
    weights = {m: max(balances.get(m, Money.zero(amount.currency)).amount, 0) for m in member_ids}
    return amount.allocate(weights)


def receipt(book: FundBook, *, key: str, line_id: int, amount: Money, member_id: int | None,
            fine: bool = False) -> JournalDraft:
    """A pay-in. A member's pay-in to the fund the group named for fines pays
    their fines: it is the group's money in that fund, never their share
    (Harry, 2026-10-05; ADR-0022). The line's resolution records who paid."""
    if member_id and fine:
        return book.draft(key, "fine_payment", line_id, [(book.cash(), D, amount), (book.retained(), C, amount)])
    credit = book.member(member_id) if member_id else book.unattributed()
    kind = "contribution" if member_id else "unattributed_receipt"
    return book.draft(key, kind, line_id, [(book.cash(), D, amount), (credit, C, amount)])


def interest(book: FundBook, *, key: str, line_id: int, amount: Money, rule: SharingRule, member_ids: list[int],
             balances: dict[int, Money]) -> JournalDraft:
    if rule is SharingRule.RETAINED:
        credits = [(book.retained(), C, amount)]
    else:
        credits = [(book.member(m), C, a) for m, a in share_pro_rata(amount, member_ids, balances).items()]
    return book.draft(key, "interest", line_id, [(book.cash(), D, amount), *credits])


def charge(book: FundBook, *, key: str, line_id: int, amount: Money, rule: SharingRule, member_ids: list[int],
           balances: dict[int, Money]) -> JournalDraft:
    if rule is SharingRule.RETAINED:
        debits = [(book.retained(), D, amount)]
    else:
        debits = [(book.member(m), D, a) for m, a in share_pro_rata(amount, member_ids, balances).items()]
    return book.draft(key, "bank_charge", line_id, [*debits, (book.cash(), C, amount)])


def _mandate_debits(book, amount, allocation, charged_member_id, member_ids, balances):
    if allocation is Allocation.MEMBER:
        return [(book.member(charged_member_id), D, amount)]
    return [(book.member(m), D, a) for m, a in share_pro_rata(amount, member_ids, balances).items()]


def authorised_payout(book: FundBook, *, key: str, line_id: int, amount: Money, allocation: Allocation,
                      charged_member_id: int | None, member_ids: list[int], balances: dict[int, Money],
                      reference: str) -> JournalDraft:
    debits = _mandate_debits(book, amount, allocation, charged_member_id, member_ids, balances)
    return book.draft(key, "withdrawal", line_id, [*debits, (book.cash(), C, amount)], memo=reference)


def unexplained_payout(book: FundBook, *, key: str, line_id: int, amount: Money) -> JournalDraft:
    return book.draft(key, "unexplained_outflow", line_id, [(book.unexplained(), D, amount), (book.cash(), C, amount)])


def payer_identified(book: FundBook, *, key: str, line_id: int, amount: Money, member_id: int,
                     fine: bool = False) -> JournalDraft:
    credit = book.retained() if fine else book.member(member_id)  # a fine paid is the group's (see ``receipt``)
    return book.draft(key, "attribution", line_id, [(book.unattributed(), D, amount), (credit, C, amount)])


def payout_explained(book: FundBook, *, key: str, line_id: int, amount: Money, allocation: Allocation,
                     charged_member_id: int | None, member_ids: list[int], balances: dict[int, Money],
                     reference: str) -> JournalDraft:
    debits = _mandate_debits(book, amount, allocation, charged_member_id, member_ids, balances)
    return book.draft(key, "outflow_explained", line_id, [*debits, (book.unexplained(), C, amount)], memo=reference)


def payout_explained_elsewhere(held: FundBook, spent: FundBook, *, key: str, line_id: int, amount: Money,
                               allocation: Allocation, charged_member_id: int | None, member_ids: list[int],
                               balances: dict[int, Money], reference: str) -> tuple[JournalDraft, JournalDraft]:
    """An outflow held as unexplained in one fund (the default) turns out to
    be a mandate spending another fund of the same bank account (ADR-0023).
    Two entries, one per fund's books: the first fund gets its cash back, the
    mandate's fund pays. The account's total cash does not move."""
    back = held.draft(f"{key}:back", "outflow_moved", line_id,
                      [(held.cash(), D, amount), (held.unexplained(), C, amount)], memo=reference)
    debits = _mandate_debits(spent, amount, allocation, charged_member_id, member_ids, balances)
    paid = spent.draft(f"{key}:paid", "outflow_explained", line_id, [*debits, (spent.cash(), C, amount)],
                       memo=reference)
    return back, paid


def opening_balances(book: FundBook, *, key: str, line_id: int, statement_balance: Money,
                     signed_off: dict[int, Money]) -> JournalDraft:
    """Bring an existing account in: members get what two correct_records holders signed
    off; anything in the bank nobody can account for is held as unattributed."""
    total = Money.zero(book.currency)
    for amount in signed_off.values():
        total += amount
    if total > statement_balance:
        raise AccountingError("Member balances add up to more than the bank balance.")
    credits = [(book.member(m), C, a) for m, a in signed_off.items() if a.is_positive]
    return book.draft(key, "opening", line_id, [(book.cash(), D, statement_balance), *credits,
                                                (book.unattributed(), C, statement_balance - total)],
                      memo="Opening balances")


def fund_transfer(source: FundBook, destination: FundBook, *, transfer_id: int, members: dict[int, Money],
                  retained: Money | None, memo_out: str, memo_in: str) -> FundTransfer:
    """Money the group decided to move between two of its funds at the same
    bank account (ADR-0024). The owners keep it: each member's share, or the
    group's own money, leaves the source fund and arrives in the destination
    for the same owner. The account's total does not move."""
    if source.external_account_id != destination.external_account_id:
        raise AccountingError("Money moves between funds held at the same bank account.")
    if bool(members) == (retained is not None):
        raise AccountingError("A transfer moves either members' money or the group's, not both and not neither.")
    total = retained if retained is not None else sum(members.values(), Money.zero(source.currency))
    take = ([(source.retained(), D, retained)] if retained is not None
            else [(source.member(m), D, a) for m, a in members.items()])
    give = ([(destination.retained(), C, retained)] if retained is not None
            else [(destination.member(m), C, a) for m, a in members.items()])
    cause = dict(cause_id=transfer_id, cause_type="governance.fund_transfer")
    return FundTransfer(
        out=source.draft(f"fund_transfer:{transfer_id}:out", TRANSFER_OUT, postings=[*take, (source.cash(), C, total)],
                         memo=memo_out, **cause),
        into=destination.draft(f"fund_transfer:{transfer_id}:in", TRANSFER_IN, memo=memo_in,
                               postings=[(destination.cash(), D, total), *give], **cause))


def transfer_shares(amount: Money, sharer_ids: list[int], balances: dict[int, Money]) -> dict[int, Money]:
    """A pro-rata transfer: each sharing member gives in proportion to what
    they hold in the source fund, and never more than they hold. Call only
    once the sharers are known to hold at least ``amount`` together."""
    holders = [m for m in sharer_ids if balances.get(m, Money.zero(amount.currency)).is_positive]
    shares = share_pro_rata(amount, holders, balances)
    if any(balances[m] < a for m, a in shares.items()):
        raise AccountingError("A pro-rata transfer would take more than a member holds.")
    return shares
