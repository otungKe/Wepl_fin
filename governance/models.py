"""Groups, their constitutions, and the chain that authorises money to move:

    Proposal -> Approvals (under the constitution in force) -> Mandate

A mandate is the only thing that makes an outflow legitimate. Anything that
leaves a group's account without one is flagged by reconciliation.
"""
import secrets

from django.db import models
from django.db.models import Q

from parties.models import Person


class Group(models.Model):
    class Segment(models.TextChoices):
        SAVINGS = "savings", "Savings / investment chama"
        WELFARE = "welfare", "Welfare group or association"
        COLLECTION = "collection", "One-off collection"

    name = models.CharField(max_length=120)
    segment = models.CharField(max_length=20, choices=Segment.choices, default=Segment.SAVINGS)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Membership(models.Model):
    class Role(models.TextChoices):
        CHAIR = "chair", "Chair"
        TREASURER = "treasurer", "Treasurer"
        SECRETARY = "secretary", "Secretary"
        MEMBER = "member", "Member"

    OFFICIALS = (Role.CHAIR, Role.TREASURER, Role.SECRETARY)

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        LEFT = "left", "Left"

    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="memberships")
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="memberships")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    # Short code members can add to a paybill reference, e.g. "M03".
    member_code = models.CharField(max_length=8)
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["group", "person"], condition=Q(status="active"),
                                    name="gov_one_active_membership"),
            models.UniqueConstraint(fields=["group", "member_code"], name="gov_member_code_unique"),
        ]

    @property
    def is_official(self):
        return self.role in self.OFFICIALS

    def __str__(self):
        return f"{self.person.display_name} [{self.role}] in {self.group_id}"


class Constitution(models.Model):
    """A versioned rulebook. A new version is a new row; old versions are never
    edited, so every decision can be checked against the rules it was made under.

    ``rules`` example::

        {
          "approvals": [
            {"up_to": "50000", "approvers": "officials", "required": 2},
            {"up_to": null,    "approvers": "members",   "required": 4}
          ],
          "allow_self_approval": false,
          "withdrawal_allocation": "pro_rata",
          "bank_charges": "pro_rata",
          "interest": "pro_rata",
          "mandate_valid_days": 14
        }
    """

    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="constitutions")
    version = models.PositiveIntegerField()
    rules = models.JSONField()
    effective_from = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["group", "version"], name="gov_constitution_version")]
        get_latest_by = "version"


class Fund(models.Model):
    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="funds")
    name = models.CharField(max_length=80)
    currency = models.CharField(max_length=3, default="KES")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["group", "name"], name="gov_fund_name")]

    def __str__(self):
        return f"{self.group.name} / {self.name}"


class Proposal(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    class Allocation(models.TextChoices):
        PRO_RATA = "pro_rata", "Shared by all members, in proportion to their balances"
        MEMBER = "member", "Charged to one member (e.g. exit payout or loan)"

    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="proposals")
    fund = models.ForeignKey(Fund, on_delete=models.PROTECT, related_name="proposals")
    constitution = models.ForeignKey(Constitution, on_delete=models.PROTECT)
    proposed_by = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="+")
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    purpose = models.CharField(max_length=200)
    payee_name = models.CharField(max_length=120)
    payee_account = models.CharField(max_length=40, help_text="Phone number or bank account")
    allocation = models.CharField(max_length=10, choices=Allocation.choices, default=Allocation.PRO_RATA)
    charged_member = models.ForeignKey(Membership, null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")
    approvers = models.CharField(max_length=10)  # "officials" or "members", from the rule used
    required_approvals = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="gov_proposal_amount_positive"),
            models.CheckConstraint(
                condition=Q(allocation="member", charged_member__isnull=False)
                | Q(allocation="pro_rata", charged_member__isnull=True),
                name="gov_proposal_allocation_consistent",
            ),
        ]


class Approval(models.Model):
    """One member's decision on a proposal. Append-only."""

    proposal = models.ForeignKey(Proposal, on_delete=models.PROTECT, related_name="approvals")
    membership = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="+")
    approve = models.BooleanField()
    source = models.CharField(max_length=20, default="app")  # app, sms, meeting
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["proposal", "membership"], name="gov_one_vote")]


def new_mandate_reference() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I
    return "WM" + "".join(secrets.choice(alphabet) for _ in range(6))


class Mandate(models.Model):
    """Authority to move a specific amount to a specific payee. The treasurer
    quotes ``reference`` in the bank narration so the outflow can be matched."""

    class Status(models.TextChoices):
        ISSUED = "issued", "Issued"
        EXECUTED = "executed", "Executed"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"

    proposal = models.OneToOneField(Proposal, on_delete=models.PROTECT, related_name="mandate")
    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="mandates")
    fund = models.ForeignKey(Fund, on_delete=models.PROTECT, related_name="mandates")
    reference = models.CharField(max_length=12, unique=True, default=new_mandate_reference)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    payee_name = models.CharField(max_length=120)
    payee_account = models.CharField(max_length=40)
    allocation = models.CharField(max_length=10, choices=Proposal.Allocation.choices)
    charged_member = models.ForeignKey(Membership, null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ISSUED)
    issued_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    executed_at = models.DateTimeField(null=True, blank=True)
    # Set when the matching outflow is found on the custodian statement.
    executed_by_line_id = models.BigIntegerField(null=True, blank=True, unique=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="gov_mandate_amount_positive")]
