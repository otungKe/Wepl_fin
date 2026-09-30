from django.db import models
from django.db.models import Q

from contexts.tenancy.contract import TenantScope
from persistence.tenancy import tenant_column

from ..domain.membership import TITLE_MAX, MembershipStatus, Segment


class Group(models.Model):
    """An independently governed group: exactly one per tenant (ADR-0010)."""

    tenant_scope = TenantScope.TENANT_SCOPED
    tenant = tenant_column()
    name = models.CharField(max_length=120)
    segment = models.CharField(max_length=20, choices=[(s, s) for s in Segment], default=Segment.SAVINGS)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant"], name="community_one_group_per_tenant")]


class Fund(models.Model):
    tenant_scope = TenantScope.TENANT_SCOPED
    tenant = tenant_column()
    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="funds")
    name = models.CharField(max_length=80)
    currency = models.CharField(max_length=3, default="KES")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["group", "name"], name="community_fund_name")]


class Membership(models.Model):
    tenant_scope = TenantScope.TENANT_SCOPED
    tenant = tenant_column()
    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="memberships")
    # Cross-context reference to identity (ADR-0004): a membership is a person's
    # relationship with a group; people are never deleted.
    person = models.ForeignKey("identity.Person", on_delete=models.PROTECT, related_name="+")
    title = models.CharField(max_length=TITLE_MAX, blank=True, default="")  # a label only (ADR-0011)
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
