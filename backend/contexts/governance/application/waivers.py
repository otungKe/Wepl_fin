"""Use cases: propose to forgive part of what one member owes a fund (their
arrears or fines), decide on it, cancel it (ADR-0022). Decided like a
withdrawal: the approval rule for the amount, one vote per member, and the
member it is for may not approve it. Nothing here moves money."""
from django.db import transaction
from django.utils import timezone

from contexts.audit.public import record
from contexts.communities.public import CommunityError, MembershipView, fund_view, members, membership
from contexts.notifications.public import notify
from contexts.shared_kernel.money import Money

from ..contract import GovernanceError, WaiverView
from ..domain.capabilities import Capability
from ..domain.contribution import WaiverOf
from ..domain.lifecycle import PROPOSAL_TRANSITIONS, ProposalStatus, ensure
from ..domain.rules import ApproverSet, ConstitutionRules
from ..domain.voting import ProposalTerms, ineligibility, tally
from ..infrastructure.models import Waiver, WaiverVote
from .capabilities import holds
from .constitution import current_constitution
from .proposals import _voter


def _terms(w: Waiver) -> ProposalTerms:
    return ProposalTerms(group_id=w.group_id, proposer_id=w.proposed_by_id, charged_member_id=w.member_id,
                         payee_account="", approvers=ApproverSet(w.approvers), required=w.required_approvals,
                         allow_self_approval=ConstitutionRules.parse(w.constitution.rules).allow_self_approval,
                         subject="waiver")


def _view(w: Waiver) -> WaiverView:
    return WaiverView(id=w.pk, group_id=w.group_id, fund_id=w.fund_id, member_id=w.member_id,
                      owed=WaiverOf(w.owed), amount=Money(w.amount, w.currency), status=ProposalStatus(w.status),
                      required_approvals=w.required_approvals, approvals=w.votes.filter(approve=True).count(),
                      decided_at=w.decided_at)


def waiver_view(waiver_id: int) -> WaiverView:
    return _view(Waiver.objects.get(pk=waiver_id))


def eligible_waiver_approvers(waiver_id: int) -> list[MembershipView]:
    w = Waiver.objects.select_related("constitution").get(pk=waiver_id)
    terms = _terms(w)
    return [m for m in members(w.group_id) if ineligibility(_voter(m), terms) is None]


def approved_waivers(fund_id: int, member_id: int) -> list[WaiverView]:
    """The member's approved waivers in a fund, in the order they were decided."""
    rows = Waiver.objects.filter(fund_id=fund_id, member_id=member_id, status=ProposalStatus.APPROVED)
    return [_view(w) for w in rows.order_by("decided_at", "id")]


@transaction.atomic  # the waiver, its approval requests and audit record commit together
def propose_waiver(proposer_id: int, fund_id: int, member_id: int, *, owed: str, amount, reason: str) -> WaiverView:
    try:
        proposer, fund, member = membership(proposer_id), fund_view(fund_id), membership(member_id)
    except CommunityError as exc:
        raise GovernanceError(str(exc)) from None
    owed, amount = WaiverOf(owed), Money.of(amount, fund.currency)
    if not proposer.is_active:
        raise GovernanceError("Only active members can propose a waiver.")
    if not (fund.group_id == member.group_id == proposer.group_id):
        raise GovernanceError("The fund and the member must both be in the proposer's group.")
    if not amount.is_positive or not reason.strip():
        raise GovernanceError("A waiver needs an amount above zero and a reason.")
    constitution = current_constitution(proposer.group_id)
    if constitution is None:
        raise GovernanceError("The group has no constitution yet.")
    rules = ConstitutionRules.parse(constitution.rules)
    if rules.contribution_rule(fund.id) is None:
        raise GovernanceError(f"{fund.name} has no contribution rule, so nothing is owed to it to waive.")
    tier = rules.tier_for(amount)
    w = Waiver.objects.create(group_id=fund.group_id, fund_id=fund.id, member_id=member.id, constitution=constitution,
                              proposed_by_id=proposer.id, owed=owed.value, amount=amount.amount,
                              currency=amount.currency, reason=reason.strip()[:200], approvers=tier.approvers.value,
                              required_approvals=tier.required)
    approvers = eligible_waiver_approvers(w.pk)
    if len(approvers) < tier.required:
        raise GovernanceError("Not enough eligible approvers for this amount under the constitution.")
    record(proposer.msisdn, "waiver.proposed", target_type="waiver", target_id=w.pk, group_id=w.group_id,
           data={"member_id": member.id, "owed": owed.value, "amount": str(amount.amount), "required": tier.required})
    for a in approvers:
        notify("waiver.approval_requested", {"msisdn": a.msisdn, "waiver_id": w.pk, "member": member.name,
                                             "owed": owed.value, "amount": str(amount.amount), "reason": w.reason},
               dedupe_key=f"waiver.approval_requested:{w.pk}:{a.id}")
    return _view(w)


@transaction.atomic  # the waiver row lock serialises votes
def decide_waiver(waiver_id: int, voter_id: int, *, approve: bool, source: str = "app") -> WaiverView:
    """One member's decision. Repeating it is a no-op; changing it is refused."""
    w = Waiver.objects.select_for_update().select_related("constitution").get(pk=waiver_id)
    voter = membership(voter_id)
    previous = WaiverVote.objects.filter(waiver=w, membership_id=voter.id).first()
    if previous is not None:
        if previous.approve == approve:
            return _view(w)
        raise GovernanceError("You have already decided on this waiver; a vote cannot be changed.")
    if w.status != ProposalStatus.OPEN:
        raise GovernanceError(f"This waiver is already {w.status}.")
    if reason := ineligibility(_voter(voter), _terms(w)):
        raise GovernanceError(f"Not allowed to decide: {reason}.")
    WaiverVote.objects.create(waiver=w, membership_id=voter.id, approve=approve, source=source)
    record(voter.msisdn, "waiver.decided", target_type="waiver", target_id=w.pk, group_id=w.group_id,
           data={"approve": approve, "source": source})
    outcome = tally(required=w.required_approvals, approvals=w.votes.filter(approve=True).count(),
                    declines=w.votes.filter(approve=False).count(), eligible=len(eligible_waiver_approvers(w.pk)))
    if outcome is not ProposalStatus.OPEN:
        _move(w, outcome)
    return _view(w)


@transaction.atomic
def cancel_waiver(waiver_id: int, actor_id: int) -> WaiverView:
    w = Waiver.objects.select_for_update().get(pk=waiver_id)
    actor = membership(actor_id)
    if actor.group_id != w.group_id or (actor.id != w.proposed_by_id and not holds(actor.id, Capability.CANCEL_PAYOUT)):
        raise GovernanceError("Only the proposer, or a member of this group granted cancel_payout, can cancel.")
    _move(w, ProposalStatus.CANCELLED)
    return _view(w)


def _move(w: Waiver, new: ProposalStatus) -> None:
    ensure(PROPOSAL_TRANSITIONS, ProposalStatus(w.status), new)
    w.status, w.decided_at = new.value, timezone.now()
    w.save(update_fields=["status", "decided_at"])
    record("system", f"waiver.{new.value}", target_type="waiver", target_id=w.pk, group_id=w.group_id)
