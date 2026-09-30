from django.db import models
from django.db.models import Q

from ..domain.membership import MembershipStatus, Role, Segment


class Group(models.Model):
    name = models.CharField(max_length=120)
    segment = models.CharField(max_length=20, choices=[(s, s) for s in Segment], default=Segment.SAVINGS)
    created_at = models.DateTimeField(auto_now_add=True)


class Fund(models.Model):
    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="funds")
    name = models.CharField(max_length=80)
    currency = models.CharField(max_length=3, default="KES")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["group", "name"], name="community_fund_name")]


class Membership(models.Model):
    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="memberships")
    # Cross-context reference to identity (ADR-0004): a membership is a person's
    # relationship with a group; people are never deleted.
    person = models.ForeignKey("identity.Person", on_delete=models.PROTECT, related_name="+")
    role = models.CharField(max_length=20, choices=[(r, r) for r in Role], default=Role.MEMBER)
    status = models.CharField(max_length=10, choices=[(s, s) for s in MembershipStatus],
                              default=MembershipStatus.ACTIVE)
    member_code = models.CharField(max_length=8)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["group", "person"], condition=Q(status="active"),
                                    name="community_one_active_membership"),
            models.UniqueConstraint(fields=["group", "member_code"], name="community_member_code_unique"),
        ]
