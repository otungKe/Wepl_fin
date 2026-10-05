"""Governance persistence. Constitutions, approvals and capability changes
are append-only (0002, 0005).

Cross-context references to communities (group, fund, membership) are
deliberate foreign keys (ADR-0004): a proposal is always made in a group, on
a fund, by a member, and none of those are ever deleted.
"""
from django.db import models
from django.db.models import Q

from contexts.tenancy.contract import TenantScope
from persistence.tenancy import tenant_column

from ..domain.capabilities import Capability
from ..domain.contribution import WaiverOf
from ..domain.lifecycle import MandateStatus, ProposalStatus
from ..domain.mandate import Allocation, new_reference

GROUP, FUND, MEMBERSHIP = "communities.Group", "communities.Fund", "communities.Membership"


def _choices(enum):
    return [(e.value, e.value) for e in enum]


class Constitution(models.Model):
    tenant_scope = TenantScope.TENANT_SCOPED
    tenant = tenant_column()
    group = models.ForeignKey(GROUP, on_delete=models.PROTECT, related_name="+")
    version = models.PositiveIntegerField()
    rules = models.JSONField()
    adopted_by = models.CharField(max_length=120)
    effective_from = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["group", "version"], name="gov_constitution_version")]


class Proposal(models.Model):
    tenant_scope = TenantScope.TENANT_SCOPED
    tenant = tenant_column()
    group = models.ForeignKey(GROUP, on_delete=models.PROTECT, related_name="+")
    fund = models.ForeignKey(FUND, on_delete=models.PROTECT, related_name="+")
    constitution = models.ForeignKey(Constitution, on_delete=models.PROTECT)
    request_key = models.CharField(max_length=80, null=True, blank=True)  # unique per tenant
    proposed_by = models.ForeignKey(MEMBERSHIP, on_delete=models.PROTECT, related_name="+")
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3, default="KES")
    purpose = models.CharField(max_length=200)
    payee_name = models.CharField(max_length=120)
    payee_account = models.CharField(max_length=40)
    allocation = models.CharField(max_length=10, choices=_choices(Allocation), default=Allocation.PRO_RATA)
    charged_member = models.ForeignKey(MEMBERSHIP, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    approvers = models.CharField(max_length=10)
    required_approvals = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=10, choices=_choices(ProposalStatus), default=ProposalStatus.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="gov_proposal_amount_positive"),
            models.UniqueConstraint(fields=["tenant", "request_key"], name="gov_proposal_request_key_unique"),
            models.CheckConstraint(condition=Q(allocation="member", charged_member__isnull=False)
                                   | Q(allocation="pro_rata", charged_member__isnull=True),
                                   name="gov_proposal_allocation_consistent"),
        ]
        # The request-key lookup, for the reason given on the outbox (ADR-0016).
        indexes = [models.Index(fields=["request_key"], name="gov_proposal_request_key")]


class Approval(models.Model):
    tenant_scope = TenantScope.TENANT_SCOPED
    tenant = tenant_column()
    proposal = models.ForeignKey(Proposal, on_delete=models.PROTECT, related_name="approvals")
    membership = models.ForeignKey(MEMBERSHIP, on_delete=models.PROTECT, related_name="+")
    approve = models.BooleanField()
    source = models.CharField(max_length=20, default="app")  # app, sms, meeting
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["proposal", "membership"], name="gov_one_vote")]


class Mandate(models.Model):
    tenant_scope = TenantScope.TENANT_SCOPED
    tenant = tenant_column()
    proposal = models.OneToOneField(Proposal, on_delete=models.PROTECT, related_name="mandate")
    group = models.ForeignKey(GROUP, on_delete=models.PROTECT, related_name="+")
    fund = models.ForeignKey(FUND, on_delete=models.PROTECT, related_name="+")
    reference = models.CharField(max_length=12, unique=True, default=new_reference)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3, default="KES")
    payee_name = models.CharField(max_length=120)
    payee_account = models.CharField(max_length=40)
    allocation = models.CharField(max_length=10, choices=_choices(Allocation))
    charged_member = models.ForeignKey(MEMBERSHIP, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=10, choices=_choices(MandateStatus), default=MandateStatus.ISSUED)
    issued_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    executed_at = models.DateTimeField(null=True, blank=True)
    # The custody statement line that executed it (an id in another context).
    executed_by_line_id = models.BigIntegerField(null=True, blank=True, unique=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="gov_mandate_amount_positive"),
            models.CheckConstraint(condition=~Q(status="executed") | Q(executed_by_line_id__isnull=False),
                                   name="gov_executed_mandate_has_line"),
        ]
        indexes = [models.Index(fields=["fund", "status", "amount"])]


class CapabilityChange(models.Model):
    """One grant or revocation of a capability to a member (ADR-0011).
    Append-only: what a member may do now is their latest change per
    capability, and the full history of who could do what stays."""

    tenant_scope = TenantScope.TENANT_SCOPED
    tenant = tenant_column()
    group = models.ForeignKey(GROUP, on_delete=models.PROTECT, related_name="+")
    membership = models.ForeignKey(MEMBERSHIP, on_delete=models.PROTECT, related_name="+")
    capability = models.CharField(max_length=30, choices=_choices(Capability))
    granted = models.BooleanField()
    changed_by = models.CharField(max_length=120)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["membership", "id"])]


class Waiver(models.Model):
    """A request to forgive part of what one member owes a fund: arrears or
    fines (ADR-0022). Decided like a withdrawal, under the approval rule for
    its amount, and the member it is for may not approve it. It moves no
    money; an approved waiver only lowers what the member is shown to owe."""

    tenant_scope = TenantScope.TENANT_SCOPED
    tenant = tenant_column()
    group = models.ForeignKey(GROUP, on_delete=models.PROTECT, related_name="+")
    fund = models.ForeignKey(FUND, on_delete=models.PROTECT, related_name="+")
    member = models.ForeignKey(MEMBERSHIP, on_delete=models.PROTECT, related_name="+")
    constitution = models.ForeignKey(Constitution, on_delete=models.PROTECT, related_name="+")
    proposed_by = models.ForeignKey(MEMBERSHIP, on_delete=models.PROTECT, related_name="+")
    owed = models.CharField(max_length=10, choices=_choices(WaiverOf))
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3, default="KES")
    reason = models.CharField(max_length=200)
    approvers = models.CharField(max_length=10)
    required_approvals = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=10, choices=_choices(ProposalStatus), default=ProposalStatus.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="gov_waiver_amount_positive")]
        indexes = [models.Index(fields=["fund", "member", "status"])]


class WaiverVote(models.Model):
    tenant_scope = TenantScope.TENANT_SCOPED
    tenant = tenant_column()
    waiver = models.ForeignKey(Waiver, on_delete=models.PROTECT, related_name="votes")
    membership = models.ForeignKey(MEMBERSHIP, on_delete=models.PROTECT, related_name="+")
    approve = models.BooleanField()
    source = models.CharField(max_length=20, default="app")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["waiver", "membership"], name="gov_one_waiver_vote")]
