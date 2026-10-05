"""Who may approve a withdrawal, and when a proposal is decided."""
from __future__ import annotations

from dataclasses import dataclass

from contexts.identity.contract import Msisdn

from .lifecycle import ProposalStatus
from .rules import ApproverSet


@dataclass(frozen=True)
class Voter:
    membership_id: int
    group_id: int
    active: bool
    designated_approver: bool  # holds APPROVE_PAYOUT
    msisdn: str


@dataclass(frozen=True)
class ProposalTerms:
    group_id: int
    proposer_id: int
    charged_member_id: int | None
    payee_account: str
    approvers: ApproverSet
    required: int
    allow_self_approval: bool
    subject: str = "payout"  # or "waiver": what the charged member would benefit from


def ineligibility(voter: Voter, terms: ProposalTerms) -> str | None:
    """Why this voter may not decide on this proposal, or None if they may."""
    if voter.group_id != terms.group_id:
        return "not a member of this group"
    if not voter.active:
        return "not an active member"
    if terms.approvers is ApproverSet.DESIGNATED and not voter.designated_approver:
        return f"only designated approvers approve {'withdrawals' if terms.subject == 'payout' else terms.subject + 's'} of this size"
    if terms.allow_self_approval:
        return None
    if voter.membership_id == terms.proposer_id:
        return "cannot approve a request they made"
    if voter.membership_id == terms.charged_member_id:
        return ("cannot approve a payout charged to themselves" if terms.subject == "payout"
                else f"cannot approve a {terms.subject} for themselves")
    payee = Msisdn.try_parse(terms.payee_account)
    if payee is not None and payee.value == voter.msisdn:
        return "cannot approve a payment to themselves"
    return None


def tally(*, required: int, approvals: int, declines: int, eligible: int) -> ProposalStatus:
    if approvals >= required:
        return ProposalStatus.APPROVED
    if eligible - declines < required:
        return ProposalStatus.REJECTED
    return ProposalStatus.OPEN
