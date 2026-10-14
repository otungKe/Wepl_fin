"""Use cases: propose to move money from one of the group's funds to another,
decide on it, cancel it, and record how custody settled it (ADR-0024).
Decided like a withdrawal: the approval rule for the amount, one vote per
member, and the member whose money it is may not approve it. Nothing here
moves money: custody books an approved transfer and reports back here."""
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from contexts.audit.public import record
from contexts.communities.public import CommunityError, MembershipView, fund_view, members, membership
from contexts.ledger.public import fund_position, member_balances
from contexts.notifications.public import notify
from contexts.shared_kernel.money import Money

from ..contract import FundTransferView, GovernanceError
from ..domain.capabilities import Capability
from ..domain.lifecycle import TRANSFER_TRANSITIONS, MandateStatus, TransferStatus, ensure
from ..domain.rules import ApproverSet, ConstitutionRules
from ..domain.transfer import TransferFrom, shortfall
from ..domain.voting import ProposalTerms, ineligibility, tally
from ..infrastructure.models import FundTransfer, Mandate, TransferVote
from .capabilities import holds
from .constitution import current_constitution
from .proposals import _voter


def _terms(t: FundTransfer) -> ProposalTerms:
    return ProposalTerms(group_id=t.group_id, proposer_id=t.proposed_by_id, charged_member_id=t.member_id,
                         payee_account="", approvers=ApproverSet(t.approvers), required=t.required_approvals,
                         allow_self_approval=ConstitutionRules.parse(t.constitution.rules).allow_self_approval,
                         subject="transfer")


def _view(t: FundTransfer) -> FundTransferView:
    return FundTransferView(id=t.pk, group_id=t.group_id, from_fund_id=t.from_fund_id, to_fund_id=t.to_fund_id,
                            source=TransferFrom(t.source), member_id=t.member_id, amount=Money(t.amount, t.currency),
                            reason=t.reason, status=TransferStatus(t.status), required_approvals=t.required_approvals,
                            approvals=t.votes.filter(approve=True).count(), decided_at=t.decided_at,
                            out_entry_id=t.out_entry_id, in_entry_id=t.in_entry_id, failure=t.failure)


def fund_transfer(transfer_id: int) -> FundTransferView:
    t = FundTransfer.objects.filter(pk=transfer_id).first()
    if t is None:  # unknown, or another group's (row-level security hides it)
        raise GovernanceError(f"Unknown fund transfer {transfer_id}.")
    return _view(t)


def approved_transfers() -> list[FundTransferView]:
    """Approved transfers custody has not booked yet, oldest first."""
    return [_view(t) for t in FundTransfer.objects.filter(status=TransferStatus.APPROVED).order_by("id")]


def eligible_transfer_approvers(transfer_id: int) -> list[MembershipView]:
    t = FundTransfer.objects.select_related("constitution").get(pk=transfer_id)
    terms = _terms(t)
    return [m for m in members(t.group_id) if ineligibility(_voter(m), terms) is None]


def committed_out(fund_id: int, *, besides: int | None = None) -> Money:
    """What the group has already promised out of a fund: issued, unexecuted
    mandates, and approved transfers not yet booked (other than ``besides``)."""
    currency = fund_view(fund_id).currency
    mandates = Mandate.objects.filter(fund_id=fund_id, status=MandateStatus.ISSUED).aggregate(v=Sum("amount"))["v"]
    transfers = (FundTransfer.objects.filter(from_fund_id=fund_id, status=TransferStatus.APPROVED)
                 .exclude(pk=besides).aggregate(v=Sum("amount"))["v"])
    return Money(mandates or 0, currency) + Money(transfers or 0, currency)


def _owners_hold(fund_id: int, source: TransferFrom, member_id: int | None, currency: str) -> Money:
    """An early, generous look: pro-rata counts every member with money in the
    fund. Custody's booking applies the group's leaver rules exactly."""
    if source is TransferFrom.RETAINED:
        return fund_position(fund_id, currency).retained
    balances = member_balances(fund_id, currency)
    if source is TransferFrom.MEMBER:
        return balances.get(member_id, Money.zero(currency))
    return sum((b for b in balances.values() if b.is_positive), Money.zero(currency))


@transaction.atomic  # the transfer, its approval requests and audit record commit together
def propose_fund_transfer(proposer_id: int, from_fund_id: int, to_fund_id: int, *, amount, source: str,
                          reason: str, member_id: int | None = None,
                          request_key: str | None = None) -> FundTransferView:
    """``request_key`` makes a retried submission return the first transfer."""
    if request_key and (existing := FundTransfer.objects.filter(request_key=request_key).first()):
        if existing.proposed_by_id != proposer_id:
            raise GovernanceError("That request key belongs to someone else's transfer.")
        return _view(existing)
    try:
        proposer, src, dst = membership(proposer_id), fund_view(from_fund_id), fund_view(to_fund_id)
        member = membership(member_id) if member_id is not None else None
    except CommunityError as exc:
        raise GovernanceError(str(exc)) from None
    source, amount = TransferFrom(source), Money.of(amount, src.currency)
    if not proposer.is_active:
        raise GovernanceError("Only active members can propose a transfer.")
    if not (src.group_id == dst.group_id == proposer.group_id):
        raise GovernanceError("Both funds must be in the proposer's group.")
    if src.id == dst.id:
        raise GovernanceError("Choose two different funds.")
    if src.currency != dst.currency:
        raise GovernanceError("Money moves only between funds of the same currency.")
    if not (src.is_open and dst.is_open):
        raise GovernanceError(f"{src.name if not src.is_open else dst.name} is closed.")
    if (source is TransferFrom.MEMBER) != (member is not None):
        raise GovernanceError("Name a member exactly when the money is one member's.")
    if member is not None and member.group_id != proposer.group_id:
        raise GovernanceError("That member is not in this group.")
    if not amount.is_positive or not reason.strip():
        raise GovernanceError("A transfer needs an amount above zero and a reason.")
    if why := shortfall(amount, owners_hold=_owners_hold(src.id, source, member_id, src.currency),
                        cash=fund_position(src.id, src.currency).cash, committed=committed_out(src.id)):
        raise GovernanceError(f"Cannot move {amount} out of {src.name}: {why}.")
    constitution = current_constitution(proposer.group_id)
    if constitution is None:
        raise GovernanceError("The group has no constitution yet.")
    tier = ConstitutionRules.parse(constitution.rules).tier_for(amount)
    try:
        t = FundTransfer.objects.create(
            group_id=src.group_id, from_fund_id=src.id, to_fund_id=dst.id, constitution=constitution,
            request_key=request_key, proposed_by_id=proposer.id, source=source.value, member_id=member_id,
            amount=amount.amount, currency=amount.currency, reason=reason.strip()[:200],
            approvers=tier.approvers.value, required_approvals=tier.required)
    except IntegrityError as exc:  # a fund closed after it was read (governance 0009)
        if getattr(getattr(exc.__cause__, "diag", None), "sqlstate", None) == "23001":
            raise GovernanceError("Money moves only between open funds.") from None
        raise
    approvers = eligible_transfer_approvers(t.pk)
    if len(approvers) < tier.required:
        raise GovernanceError("Not enough eligible approvers for this amount under the constitution.")
    record(proposer.msisdn, "fund_transfer.proposed", target_type="fund_transfer", target_id=t.pk,
           group_id=t.group_id, data={"from_fund": src.id, "to_fund": dst.id, "source": source.value,
                                      "member_id": member_id, "amount": str(amount.amount), "required": tier.required})
    for a in approvers:
        notify("fund_transfer.approval_requested",
               {"msisdn": a.msisdn, "transfer_id": t.pk, "amount": str(amount.amount), "from": src.name,
                "to": dst.name, "reason": t.reason}, dedupe_key=f"fund_transfer.approval_requested:{t.pk}:{a.id}")
    return _view(t)


@transaction.atomic  # the transfer row lock serialises votes
def decide_fund_transfer(transfer_id: int, voter_id: int, *, approve: bool, source: str = "app") -> FundTransferView:
    """One member's decision. Repeating it is a no-op; changing it is refused.
    Once approved, custody books it (``custody.public.book_fund_transfer``)."""
    t = FundTransfer.objects.select_for_update(of=("self",)).select_related("constitution").get(pk=transfer_id)
    voter = membership(voter_id)
    previous = TransferVote.objects.filter(transfer=t, membership_id=voter.id).first()
    if previous is not None:
        if previous.approve == approve:
            return _view(t)
        raise GovernanceError("You have already decided on this transfer; a vote cannot be changed.")
    if t.status != TransferStatus.OPEN:
        raise GovernanceError(f"This transfer is already {t.status}.")
    if reason := ineligibility(_voter(voter), _terms(t)):
        raise GovernanceError(f"Not allowed to decide: {reason}.")
    TransferVote.objects.create(transfer=t, membership_id=voter.id, approve=approve, source=source)
    record(voter.msisdn, "fund_transfer.decided", target_type="fund_transfer", target_id=t.pk, group_id=t.group_id,
           data={"approve": approve, "source": source})
    outcome = tally(required=t.required_approvals, approvals=t.votes.filter(approve=True).count(),
                    declines=t.votes.filter(approve=False).count(), eligible=len(eligible_transfer_approvers(t.pk)))
    if outcome.value != TransferStatus.OPEN:
        _move(t, TransferStatus(outcome.value))
    return _view(t)


@transaction.atomic
def cancel_fund_transfer(transfer_id: int, actor_id: int) -> FundTransferView:
    t = FundTransfer.objects.select_for_update().get(pk=transfer_id)
    actor = membership(actor_id)
    if actor.group_id != t.group_id or (actor.id != t.proposed_by_id and not holds(actor.id, Capability.CANCEL_PAYOUT)):
        raise GovernanceError("Only the proposer, or a member of this group granted cancel_payout, can cancel.")
    _move(t, TransferStatus.CANCELLED)
    return _view(t)


def settle_fund_transfer(transfer_id: int, *, entries: tuple[int, int] | None = None,
                         failure: str = "") -> bool:
    """Record custody's outcome: booked as the ledger's two ``entries``, or
    failed for the reason given. Returns False if it was no longer approved
    (another worker settled it). Call inside the booking's transaction."""
    new = TransferStatus.BOOKED if entries else TransferStatus.FAILED
    ensure(TRANSFER_TRANSITIONS, TransferStatus.APPROVED, new)
    out_id, in_id = entries or (None, None)
    won = FundTransfer.objects.filter(pk=transfer_id, status=TransferStatus.APPROVED).update(
        status=new.value, settled_at=timezone.now(), out_entry_id=out_id, in_entry_id=in_id,
        failure=failure[:255]) == 1
    if won:
        t = FundTransfer.objects.get(pk=transfer_id)
        record("system", f"fund_transfer.{new.value}", target_type="fund_transfer", target_id=t.pk,
               group_id=t.group_id, data={"entries": [out_id, in_id]} if entries else {"failure": failure[:255]})
        payload = {"group_id": t.group_id, "transfer_id": t.pk, "amount": str(t.amount), "failure": t.failure,
                   "from": fund_view(t.from_fund_id).name, "to": fund_view(t.to_fund_id).name}
        notify(f"fund_transfer.{new.value}", payload,
               dedupe_key=f"fund_transfer.{new.value}:{t.pk}")
    return won


def _move(t: FundTransfer, new: TransferStatus) -> None:
    ensure(TRANSFER_TRANSITIONS, TransferStatus(t.status), new)
    t.status, t.decided_at = new.value, timezone.now()
    t.save(update_fields=["status", "decided_at"])
    record("system", f"fund_transfer.{new.value}", target_type="fund_transfer", target_id=t.pk, group_id=t.group_id)
