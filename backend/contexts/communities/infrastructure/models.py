from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from contexts.tenancy.contract import TenantScope
from persistence.tenancy import tenant_column

from ..domain.fund import CURRENCIES, FundStatus
from ..domain.membership import TITLE_MAX, MembershipStatus


class Group(models.Model):
    """An independently governed group: exactly one per tenant (ADR-0010)."""

    tenant_scope = TenantScope.TENANT_SCOPED
    tenant = tenant_column()
    name = models.CharField(max_length=120)
    # The last member sequence handed out. Only ever increases (0006), so a
    # member code is never allocated twice, whatever happens to memberships.
    last_member_sequence = models.PositiveIntegerField(default=0, db_default=0)
    # Five digits members quote, before their own mobile number, when paying
    # into the pooled collection account (ADR-0018): 55555#0712597024. Drawn
    # by the database at founding, never changed (0014, 0015), unique.
    payment_code = models.CharField(max_length=5, unique=True, editable=False,
                                    db_default=models.Func(function="communities_new_payment_code",
                                                           output_field=models.CharField()))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant"], name="community_one_group_per_tenant")]


class Fund(models.Model):
    tenant_scope = TenantScope.TENANT_SCOPED
    tenant = tenant_column()
    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="funds")
    name = models.CharField(max_length=80)
    currency = models.CharField(max_length=3, default="KES")
    status = models.CharField(max_length=10, choices=[(s.value, s.value) for s in FundStatus],
                              default=FundStatus.OPEN.value, db_default=FundStatus.OPEN.value)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # "Savings" and "savings" are one fund to members; a closed fund's
            # name is free again (Harry, 2026-10-01)
            models.UniqueConstraint("group", Lower("name"), condition=Q(status="open"),
                                    name="community_open_fund_name_any_case"),
            models.CheckConstraint(condition=Q(currency__in=CURRENCIES), name="community_fund_currency"),
        ]


class Membership(models.Model):
    """Never deleted. Its group, person, code and joining time never change,
    and its status only goes from active to left (0006)."""

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
