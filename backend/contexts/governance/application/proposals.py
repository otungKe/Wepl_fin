"""Use cases: propose a withdrawal, decide on it, cancel it."""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from contexts.audit.public import record
from contexts.communities.public import MembershipView, fund_view, members, membership
from contexts.notifications.public import notify
from contexts.shared_kernel.money import Money

from ..contract import GovernanceError, ProposalView
from ..domain.capabilities import Capability
from ..domain.lifecycle import PROPOSAL_TRANSITIONS, ProposalStatus, ensure
from ..domain.mandate import Allocation
from ..domain.rules import ApproverSet, ConstitutionRules
from ..domain.voting import ProposalTerms, Voter, ineligibility, tally
from ..infrastructure.models import Approval, Mandate, Proposal
from .capabilities import holds
from .constitution import current_constitution


def _voter(m: MembershipView) -> Voter:
    return Voter(membership_id=m.id, group_id=m.group_id, active=m.is_active, msisdn=m.msisdn,
                 designated_approver=holds(m.id, Capability.APPROVE_PAYOUT))


def _terms(p: Proposal) -> ProposalTerms:
    return ProposalTerms(group_id=p.group_id, proposer_id=p.proposed_by_id, charged_member_id=p.charged_member_id,
                         payee_account=p.payee_account, approvers=ApproverSet(p.approvers),
                         required=p.required_approvals,
                         allow_self_approval=ConstitutionRules.parse(p.constitution.rules).allow_self_approval)


def eligible_approvers(proposal_id: int) -> list[MembershipView]:
    p = Proposal.objects.select_related("constitution").get(pk=proposal_id)
    terms = _terms(p)
    return [m for m in members(p.group_id) if ineligibility(_voter(m), terms) is None]


def proposal_view(proposal_id: int) -> ProposalView:
    p = Proposal.objects.get(pk=proposal_id)
    mandate = Mandate.objects.filter(proposal=p).values_list("reference", flat=True).first()
    return ProposalView(id=p.pk, group_id=p.group_id, fund_id=p.fund_id, amount=Money(p.amount, p.currency),
                        status=ProposalStatus(p.status), required_approvals=p.required_approvals,
                        approvals=p.approvals.filter(approve=True).count(), mandate_reference=mandate)


@transaction.atomic  # proposal, its approval requests and audit record commit together
def propose_withdrawal(proposer_id: int, fund_id: int, *, amount, purpose: str, payee_name: str, payee_account: str,
                       charged_member_id: int | None = None, request_key: str | None = None) -> ProposalView:
    """``request_key`` makes a retried submission return the first proposal."""
    if request_key:
        existing = Proposal.objects.filter(request_key=request_key).first()
        if existing:
            if existing.proposed_by_id != proposer_id:
                raise GovernanceError("That request key belongs to someone else's proposal.")
            return proposal_view(existing.pk)
    proposer, fund = membership(proposer_id), fund_view(fund_id)
    amount = Money.of(amount, fund.currency)
    if not proposer.is_active:
        raise GovernanceError("Only active members can propose withdrawals.")
    if fund.group_id != proposer.group_id:
        raise GovernanceError("That fund belongs to another group.")
    if not amount.is_positive:
        raise GovernanceError("Amount must be positive.")
    if charged_member_id is not None and membership(charged_member_id).group_id != proposer.group_id:
        raise GovernanceError("The charged member must belong to the same group.")
    constitution = current_constitution(proposer.group_id)
    if constitution is None:
        raise GovernanceError("The group has no constitution yet.")
    tier = ConstitutionRules.parse(constitution.rules).tier_for(amount)
    p = Proposal.objects.create(
        group_id=proposer.group_id, fund_id=fund.id, constitution=constitution, request_key=request_key,
        proposed_by_id=proposer.id, amount=amount.amount, currency=amount.currency, purpose=purpose,
        payee_name=payee_name, payee_account=payee_account, charged_member_id=charged_member_id,
        allocation=Allocation.MEMBER if charged_member_id else Allocation.PRO_RATA,
        approvers=tier.approvers.value, required_approvals=tier.required)
    approvers = eligible_approvers(p.pk)
    if len(approvers) < tier.required:
        raise GovernanceError("Not enough eligible approvers for this amount under the constitution.")
    record(proposer.msisdn, "proposal.created", target_type="proposal", target_id=p.pk, group_id=p.group_id,
           data={"amount": str(amount.amount), "tier": tier.approvers.value, "required": tier.required,
                 "constitution_version": constitution.version})
    for a in approvers:
        notify("approval.requested", {"msisdn": a.msisdn, "proposal_id": p.pk, "amount": str(amount.amount),
                                      "purpose": purpose, "payee": payee_name},
               dedupe_key=f"approval.requested:{p.pk}:{a.id}")
    return proposal_view(p.pk)


@transaction.atomic  # the proposal row lock serialises votes; a mandate is issued in the same commit
def decide(proposal_id: int, voter_id: int, *, approve: bool, source: str = "app") -> ProposalView:
    """Record one member's decision. Repeating the same decision is a no-op,
    so a resent SMS reply is harmless; changing a recorded vote is refused."""
    p = Proposal.objects.select_for_update().select_related("constitution").get(pk=proposal_id)
    voter = membership(voter_id)
    previous = Approval.objects.filter(proposal=p, membership_id=voter.id).first()
    if previous is not None:
        if previous.approve == approve:
            return proposal_view(p.pk)
        raise GovernanceError("You have already decided on this proposal; a vote cannot be changed.")
    if p.status != ProposalStatus.OPEN:
        raise GovernanceError(f"This proposal is already {p.status}.")
    reason = ineligibility(_voter(voter), _terms(p))
    if reason:
        raise GovernanceError(f"Not allowed to decide: {reason}.")
    Approval.objects.create(proposal=p, membership_id=voter.id, approve=approve, source=source)
    record(voter.msisdn, "proposal.decided", target_type="proposal", target_id=p.pk, group_id=p.group_id,
           data={"approve": approve, "source": source})
    outcome = tally(required=p.required_approvals, approvals=p.approvals.filter(approve=True).count(),
                    declines=p.approvals.filter(approve=False).count(), eligible=len(eligible_approvers(p.pk)))
    if outcome is not ProposalStatus.OPEN:
        _move(p, outcome)
    if outcome is ProposalStatus.APPROVED:
        _issue_mandate(p)
    return proposal_view(p.pk)


@transaction.atomic
def cancel_proposal(proposal_id: int, actor_id: int) -> ProposalView:
    p = Proposal.objects.select_for_update().get(pk=proposal_id)
    actor = membership(actor_id)
    if actor.group_id != p.group_id or (actor.id != p.proposed_by_id and not holds(actor.id, Capability.CANCEL_PAYOUT)):
        raise GovernanceError("Only the proposer, or a member of this group granted cancel_payout, can cancel.")
    _move(p, ProposalStatus.CANCELLED)
    record(actor.msisdn, "proposal.cancelled", target_type="proposal", target_id=p.pk, group_id=p.group_id)
    return proposal_view(p.pk)


def _move(p: Proposal, new: ProposalStatus) -> None:
    ensure(PROPOSAL_TRANSITIONS, ProposalStatus(p.status), new)
    p.status, p.decided_at = new.value, timezone.now()
    p.save(update_fields=["status", "decided_at"])
    record("system", f"proposal.{new.value}", target_type="proposal", target_id=p.pk, group_id=p.group_id)


def _issue_mandate(p: Proposal) -> None:
    days = ConstitutionRules.parse(p.constitution.rules).mandate_valid_days
    m = Mandate.objects.create(proposal=p, group_id=p.group_id, fund_id=p.fund_id, amount=p.amount,
                               currency=p.currency, payee_name=p.payee_name, payee_account=p.payee_account,
                               allocation=p.allocation, charged_member_id=p.charged_member_id,
                               expires_at=timezone.now() + timedelta(days=days))
    record("system", "mandate.issued", target_type="mandate", target_id=m.pk, group_id=p.group_id,
           data={"reference": m.reference, "amount": str(m.amount)})
    notify("mandate.issued", {"group_id": p.group_id, "reference": m.reference, "amount": str(m.amount),
                              "payee": m.payee_name, "purpose": p.purpose}, dedupe_key=f"mandate.issued:{m.pk}")
