"""Use case: book a move between two of a group's funds once the group has
approved it (ADR-0024). Both funds' money is at the group's one bank
account, so nothing reaches the bank: the source fund's books give the money
up and the destination's take it, for the same owners. If the money is no
longer there to move, the transfer fails and nothing is posted."""
from django.db import transaction

from contexts.audit.public import operation
from contexts.communities.public import fund_view
from contexts.governance.public import (FundTransferView, TransferFrom, TransferStatus, approved_transfers,
                                        committed_out, fund_transfer, settle_fund_transfer, shortfall)
from contexts.ledger.public import account_balance, cash_by_fund, post_transfer
from contexts.shared_kernel.money import Money

from ..contract import CustodyError
from ..domain import accounting
from ..domain.sharing import Event
from ..infrastructure.models import ExternalAccount
from . import bookkeeping as bk


@transaction.atomic  # the account lock, both entries and the settlement commit together
def book_fund_transfer(transfer_id: int) -> FundTransferView:
    """Book an approved transfer, or fail it with the reason. Booking again
    returns the transfer as it is: it is booked once."""
    group_id = fund_transfer(transfer_id).group_id
    # Lock the group's open account(s): ingestion takes the same lock, so no
    # pay-in, payout or other transfer changes the funds while this one books.
    accounts = list(ExternalAccount.objects.select_for_update()
                    .filter(group_id=group_id, closed_at__isnull=True).order_by("pk"))
    t = fund_transfer(transfer_id)  # read again under the lock
    if t.status is TransferStatus.BOOKED:
        return t
    if t.status is not TransferStatus.APPROVED:
        raise CustodyError(f"Only an approved transfer can be booked; this one is {t.status}.")
    with operation("custody.book_fund_transfer", actor="system"):
        src, dst = fund_view(t.from_fund_id), fund_view(t.to_fund_id)
        if len(accounts) != 1:
            why = ("the group has no open bank account" if not accounts
                   else "the group has more than one open bank account")
        elif not (src.is_open and dst.is_open):
            why = f"{src.name if not src.is_open else dst.name} is closed"
        else:
            why, members, retained = _owners(accounts[0], t)
        if why:
            settle_fund_transfer(t.id, failure=f"Cannot move {t.amount} from {src.name} to {dst.name}: {why}.")
            return fund_transfer(t.id)
        ea = accounts[0]
        pair = accounting.fund_transfer(bk.book(ea, src.id), bk.book(ea, dst.id), transfer_id=t.id, members=members,
                                        retained=retained, memo_out=f"Moved to {dst.name}",
                                        memo_in=f"Moved from {src.name}")
        if not settle_fund_transfer(t.id, entries=post_transfer(pair)):
            raise CustodyError(f"Fund transfer {t.id} was settled by someone else.")  # rolls the entries back
    return fund_transfer(t.id)


def _owners(ea: ExternalAccount, t: FundTransferView) -> tuple[str | None, dict[int, Money], Money | None]:
    """Whose money moves, and how much each gives; or why it cannot move."""
    zero = Money.zero(t.amount.currency)
    cash = cash_by_fund(ea.pk, ea.currency).get(t.from_fund_id, zero)
    committed = committed_out(t.from_fund_id, besides=t.id)
    if t.source is TransferFrom.RETAINED:
        held = account_balance(bk.book(ea, t.from_fund_id).retained())
        return shortfall(t.amount, owners_hold=held, cash=cash, committed=committed), {}, t.amount
    if t.source is TransferFrom.MEMBER:
        own = account_balance(bk.book(ea, t.from_fund_id).member(t.member_id))
        sharers, balances = [t.member_id], {t.member_id: own}
    else:  # the members who would share a pro-rata payout from the fund, under the group's leaver rules
        sharers, balances = bk.sharing_facts(ea, t.from_fund_id, at=t.decided_at, event=Event.PAYOUT,
                                             approved_at=t.decided_at)
    held = sum((balances[m] for m in sharers if m in balances and balances[m].is_positive), zero)
    if why := shortfall(t.amount, owners_hold=held, cash=cash, committed=committed):
        return why, {}, None
    if t.source is TransferFrom.MEMBER:
        return None, {t.member_id: t.amount}, None
    return None, accounting.transfer_shares(t.amount, sharers, balances), None


def book_approved_transfers() -> tuple[int, int]:
    """Book every approved transfer in the current tenant, oldest first.
    Returns (booked, failed). The nightly run calls this, so an approval
    whose booking was missed is booked the next night."""
    booked = failed = 0
    for t in approved_transfers():
        result = book_fund_transfer(t.id)
        booked += result.status is TransferStatus.BOOKED
        failed += result.status is TransferStatus.FAILED
    return booked, failed
