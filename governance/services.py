"""Governance use cases. Every state change runs in one transaction and is
written to the audit log."""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from parties.models import Person, normalize_msisdn
from platform_core import audit, outbox
from wepl.money import to_money

from .models import Approval, Constitution, Fund, Group, Mandate, Membership, Proposal

APPROVER_SETS = ("officials", "members")


class GovernanceError(ValidationError):
    pass


# ---------------------------------------------------------------- constitution

def validate_rules(rules: dict) -> dict:
    """Check a constitution's rules and return them normalised."""
    approvals = rules.get("approvals")
    if not approvals:
        raise GovernanceError("A constitution needs at least one approval rule.")
    normalised, last_cap = [], Decimal("-1")
    for i, rule in enumerate(approvals):
        up_to = rule.get("up_to")
        if up_to is not None:
            up_to = to_money(up_to)
            if up_to <= last_cap:
                raise GovernanceError("Approval rules must be in increasing order of amount.")
            last_cap = up_to
        elif i != len(approvals) - 1:
            raise GovernanceError("Only the last approval rule may have no upper limit.")
        if rule.get("approvers") not in APPROVER_SETS:
            raise GovernanceError(f"approvers must be one of {APPROVER_SETS}.")
        required = int(rule.get("required", 0))
        if required < 1:
            raise GovernanceError("Each approval rule needs at least one approval.")
        normalised.append({"up_to": str(up_to) if up_to is not None else None,
                           "approvers": rule["approvers"], "required": required})
    if approvals[-1].get("up_to") is not None:
        raise GovernanceError("The last approval rule must have no upper limit.")
    choice = lambda key, allowed, default: _choice(rules, key, allowed, default)
    return {
        "approvals": normalised,
        "allow_self_approval": bool(rules.get("allow_self_approval", False)),
        "withdrawal_allocation": choice("withdrawal_allocation", ("pro_rata",), "pro_rata"),
        "bank_charges": choice("bank_charges", ("pro_rata", "retained"), "pro_rata"),
        "interest": choice("interest", ("pro_rata", "retained"), "pro_rata"),
        "mandate_valid_days": int(rules.get("mandate_valid_days", 14)),
    }


def _choice(rules, key, allowed, default):
    value = rules.get(key, default)
    if value not in allowed:
        raise GovernanceError(f"{key} must be one of {allowed}.")
    return value


def current_constitution(group: Group) -> Constitution:
    return group.constitutions.order_by("-version").first()


@transaction.atomic
def adopt_constitution(group: Group, rules: dict, *, actor: str) -> Constitution:
    """Adopt a new constitution version. (Pilot onboarding: officials sign it
    off on paper. Later versions will themselves go through a proposal.)"""
    rules = validate_rules(rules)
    latest = Constitution.objects.select_for_update().filter(group=group).order_by("-version").first()
    version = (latest.version + 1) if latest else 1
    constitution = Constitution.objects.create(group=group, version=version, rules=rules)
    audit.record(actor, "constitution.adopted", constitution, {"version": version})
    return constitution


# ---------------------------------------------------------------- groups

@transaction.atomic
def create_group(name: str, *, segment: str = Group.Segment.SAVINGS, fund_name: str = "Main fund",
                 actor: str) -> tuple[Group, Fund]:
    group = Group.objects.create(name=name, segment=segment)
    fund = Fund.objects.create(group=group, name=fund_name)
    audit.record(actor, "group.created", group, {"fund_id": fund.pk})
    return group, fund


@transaction.atomic
def add_member(group: Group, *, msisdn: str, name: str, role: str = Membership.Role.MEMBER,
               actor: str) -> Membership:
    person, _ = Person.objects.get_or_create(
        msisdn=normalize_msisdn(msisdn), defaults={"display_name": name})
    Group.objects.select_for_update().get(pk=group.pk)  # serialise member codes
    code = f"M{group.memberships.count() + 1:02d}"
    membership = Membership.objects.create(group=group, person=person, role=role, member_code=code)
    audit.record(actor, "member.added", membership, {"role": role, "code": code})
    return membership


# ---------------------------------------------------------------- proposals

def _rule_for(constitution: Constitution, amount: Decimal) -> dict:
    for rule in constitution.rules["approvals"]:
        if rule["up_to"] is None or amount <= Decimal(rule["up_to"]):
            return rule
    raise GovernanceError("No approval rule covers this amount.")  # unreachable if validated


def _eligible(proposal: Proposal, membership: Membership) -> bool:
    if membership.status != Membership.Status.ACTIVE or membership.group_id != proposal.group_id:
        return False
    if proposal.approvers == "officials" and not membership.is_official:
        return False
    return True


def eligible_approvers(proposal: Proposal) -> list[Membership]:
    members = proposal.group.memberships.filter(status=Membership.Status.ACTIVE).select_related("person")
    return [m for m in members if _eligible(proposal, m) and _may_vote(proposal, m)]


def _may_vote(proposal: Proposal, membership: Membership) -> bool:
    if proposal.constitution.rules.get("allow_self_approval"):
        return True
    beneficiary = {proposal.proposed_by_id, proposal.charged_member_id}
    # A member cannot approve money going to themselves or a request they made.
    payee_is_member = False
    try:
        payee_is_member = normalize_msisdn(proposal.payee_account) == membership.person.msisdn
    except ValidationError:
        pass
    return membership.pk not in beneficiary and not payee_is_member


@transaction.atomic
def propose_withdrawal(membership: Membership, fund: Fund, *, amount, purpose: str, payee_name: str,
                       payee_account: str, charged_member: Membership | None = None) -> Proposal:
    if membership.status != Membership.Status.ACTIVE:
        raise GovernanceError("Only active members can propose withdrawals.")
    if fund.group_id != membership.group_id:
        raise GovernanceError("That fund belongs to another group.")
    amount = to_money(amount)
    if amount <= 0:
        raise GovernanceError("Amount must be positive.")
    if charged_member and charged_member.group_id != membership.group_id:
        raise GovernanceError("The charged member must belong to the same group.")
    constitution = current_constitution(membership.group)
    if constitution is None:
        raise GovernanceError("The group has no constitution yet.")
    rule = _rule_for(constitution, amount)
    proposal = Proposal.objects.create(
        group=membership.group, fund=fund, constitution=constitution, proposed_by=membership,
        amount=amount, purpose=purpose, payee_name=payee_name, payee_account=payee_account,
        allocation=Proposal.Allocation.MEMBER if charged_member else Proposal.Allocation.PRO_RATA,
        charged_member=charged_member, approvers=rule["approvers"], required_approvals=rule["required"],
    )
    audit.record(membership.person.msisdn, "proposal.created", proposal,
                 {"amount": str(amount), "rule": rule, "constitution_version": constitution.version})
    if len(eligible_approvers(proposal)) < proposal.required_approvals:
        raise GovernanceError("Not enough eligible approvers for this amount under the constitution.")
    for approver in eligible_approvers(proposal):
        outbox.emit("approval.requested", {
            "msisdn": approver.person.msisdn, "group": proposal.group.name,
            "proposal_id": proposal.pk, "amount": str(amount), "purpose": purpose, "payee": payee_name,
        })
    return proposal


@transaction.atomic
def decide(proposal: Proposal, membership: Membership, *, approve: bool, source: str = "app") -> Proposal:
    """Record one member's decision. When the constitution's threshold is met,
    the mandate is issued in the same transaction."""
    proposal = Proposal.objects.select_for_update().select_related("constitution", "group").get(pk=proposal.pk)
    if proposal.status != Proposal.Status.OPEN:
        raise GovernanceError(f"This proposal is already {proposal.status}.")
    if not _eligible(proposal, membership):
        raise GovernanceError("You are not eligible to decide on this proposal.")
    if not _may_vote(proposal, membership):
        raise GovernanceError("You cannot approve a withdrawal that benefits you or that you proposed.")
    if Approval.objects.filter(proposal=proposal, membership=membership).exists():
        raise GovernanceError("You have already decided on this proposal.")
    Approval.objects.create(proposal=proposal, membership=membership, approve=approve, source=source)
    audit.record(membership.person.msisdn, "proposal.decided", proposal,
                 {"approve": approve, "source": source})

    approvals = proposal.approvals.filter(approve=True).count()
    declines = proposal.approvals.filter(approve=False).count()
    eligible = len(eligible_approvers(proposal))
    if approvals >= proposal.required_approvals:
        _issue_mandate(proposal)
    elif eligible - declines < proposal.required_approvals:
        proposal.status = Proposal.Status.REJECTED
        proposal.decided_at = timezone.now()
        proposal.save(update_fields=["status", "decided_at"])
        audit.record("system", "proposal.rejected", proposal, {"declines": declines})
    return proposal


def _issue_mandate(proposal: Proposal) -> Mandate:
    proposal.status = Proposal.Status.APPROVED
    proposal.decided_at = timezone.now()
    proposal.save(update_fields=["status", "decided_at"])
    days = proposal.constitution.rules.get("mandate_valid_days", 14)
    mandate = Mandate.objects.create(
        proposal=proposal, group=proposal.group, fund=proposal.fund, amount=proposal.amount,
        payee_name=proposal.payee_name, payee_account=proposal.payee_account,
        allocation=proposal.allocation, charged_member=proposal.charged_member,
        expires_at=timezone.now() + timedelta(days=days),
    )
    audit.record("system", "mandate.issued", mandate,
                 {"reference": mandate.reference, "amount": str(mandate.amount)})
    outbox.emit("mandate.issued", {
        "group": proposal.group.name, "reference": mandate.reference, "amount": str(mandate.amount),
        "payee": mandate.payee_name, "purpose": proposal.purpose,
    })
    return mandate


@transaction.atomic
def cancel_proposal(proposal: Proposal, membership: Membership) -> Proposal:
    proposal = Proposal.objects.select_for_update().get(pk=proposal.pk)
    if proposal.status != Proposal.Status.OPEN:
        raise GovernanceError("Only open proposals can be cancelled.")
    if membership.pk != proposal.proposed_by_id and not membership.is_official:
        raise GovernanceError("Only the proposer or an official can cancel.")
    proposal.status = Proposal.Status.CANCELLED
    proposal.decided_at = timezone.now()
    proposal.save(update_fields=["status", "decided_at"])
    audit.record(membership.person.msisdn, "proposal.cancelled", proposal)
    return proposal


# ---------------------------------------------------------------- mandates

def claim_mandate(mandate_id: int, *, line_id: int, when) -> bool:
    """Mark an issued mandate as executed by a statement line. Returns False if
    it was not claimable (already executed, cancelled or expired). A conditional
    UPDATE makes this safe if two workers see the same outflow."""
    updated = Mandate.objects.filter(pk=mandate_id, status=Mandate.Status.ISSUED).update(
        status=Mandate.Status.EXECUTED, executed_at=when, executed_by_line_id=line_id)
    return updated == 1


def expire_mandates(now=None) -> int:
    now = now or timezone.now()
    return Mandate.objects.filter(status=Mandate.Status.ISSUED, expires_at__lt=now).update(
        status=Mandate.Status.EXPIRED)
