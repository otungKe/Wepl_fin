from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower, Now

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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant"], name="community_one_group_per_tenant")]


class Fund(models.Model):
    tenant_scope = TenantScope.TENANT_SCOPED
    tenant = tenant_column()
    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="funds")
    name = models.CharField(max_length=80)
    currency = models.CharField(max_length=3, default="KES")
    # What members add to a pay-in reference to send money to this fund
    # (ADR-0023). Optional. Communities keeps no "default fund": which fund
    # takes a pay-in quoting no code is custody's (the fund its bank account
    # was linked with). Once used, a code is this fund's for good (FundCode).
    code = models.CharField(max_length=6, null=True, blank=True)
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
            # one meaning per code among the group's open funds; a closed fund's code is free again
            models.UniqueConstraint("group", "code", condition=Q(status="open", code__isnull=False),
                                    name="community_open_fund_code"),
            models.CheckConstraint(condition=Q(code__isnull=True) | Q(code__regex=r"^[A-Z]{3,6}$"),
                                   name="community_fund_code_letters"),
            models.CheckConstraint(condition=Q(status__in=[s.value for s in FundStatus]),
                                   name="community_fund_status"),
        ]


class FundCode(models.Model):
    """Every code each of the group's funds has ever had (ADR-0026). Written
    by PostgreSQL when a fund takes a code (communities 0017), never changed
    or deleted, so a code a payer may still quote can never come to mean
    another fund: not after a change of code, not after the fund closes."""

    tenant_scope = TenantScope.TENANT_SCOPED
    tenant = tenant_column()
    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="+")
    code = models.CharField(max_length=6)
    fund = models.ForeignKey(Fund, on_delete=models.PROTECT, related_name="+")
    first_used_at = models.DateTimeField(db_default=Now())

    class Meta:
        constraints = [models.UniqueConstraint(fields=["group", "code"], name="community_fund_code_reserved")]


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
    # When the spell ended: set exactly when it is left, never changed (0014).
    left_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["group", "person"], condition=Q(status="active"),
                                    name="community_one_active_membership"),
            models.UniqueConstraint(fields=["group", "member_code"], name="community_member_code_unique"),
            models.CheckConstraint(condition=Q(status__in=[s.value for s in MembershipStatus]),
                                   name="community_membership_status"),
            models.CheckConstraint(condition=Q(left_at__isnull=True) | Q(left_at__gte=models.F("joined_at")),
                                   name="community_left_after_joining"),
        ]
