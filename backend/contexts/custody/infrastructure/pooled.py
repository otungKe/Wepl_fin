"""Persistence for WEPL's pooled collection account (ADR-0018). Platform
data about many tenants at once: forced row-level security admits only a
declared cross-tenant operation (custody 0007), so code acting for a group
sees none of it and no group sees another's payments. Imported by
``models``."""
from django.db import models
from django.db.models import Q

from contexts.tenancy.contract import TenantScope

from ..domain.statement import LineKind


class CollectionAccount(models.Model):
    """WEPL's own account at the custodian, into which many groups collect."""

    tenant_scope = TenantScope.SYSTEM
    institution = models.CharField(max_length=40)
    account_number = models.CharField(max_length=40)
    account_name = models.CharField(max_length=120)
    connector = models.CharField(max_length=40)
    currency = models.CharField(max_length=3, default="KES")
    opened_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["institution", "account_number"],
                                               name="custody_collection_account_unique")]


class Collection(models.Model):
    """One transaction on the pooled account, as the custodian reported it.
    Append-only, like a statement line."""

    tenant_scope = TenantScope.SYSTEM
    account = models.ForeignKey(CollectionAccount, on_delete=models.PROTECT, related_name="collections")
    external_id = models.CharField(max_length=64)
    sequence = models.BigIntegerField()
    posted_at = models.DateTimeField()
    kind = models.CharField(max_length=12, choices=[(k.value, k.value) for k in LineKind])
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    narration = models.CharField(max_length=255, blank=True, default="")
    reference = models.CharField(max_length=64, blank=True, default="")
    counterparty_name = models.CharField(max_length=120, blank=True, default="")
    counterparty_msisdn = models.CharField(max_length=16, blank=True, default="")
    running_balance = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["account", "external_id"], name="custody_collection_unique"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="custody_collection_amount_positive"),
        ]
        indexes = [models.Index(fields=["account", "sequence"])]


class CollectionRouting(models.Model):
    """Where a pooled transaction went: one fund's sub-account, or held at
    platform level. Append-only: a held transaction routed later gets a new
    row, and it can be routed only once."""

    class Outcome(models.TextChoices):
        ROUTED = "routed", "Routed to one fund's sub-account"
        HELD = "held", "Held: belongs to no group yet"

    tenant_scope = TenantScope.SYSTEM
    collection = models.ForeignKey(Collection, on_delete=models.PROTECT, related_name="routings")
    outcome = models.CharField(max_length=8, choices=Outcome.choices)
    # Plain ids: a platform row naming one tenant's rows (ADR-0004).
    routed_to_tenant = models.BigIntegerField(null=True, blank=True)
    external_account_id = models.BigIntegerField(null=True, blank=True)
    sub_sequence = models.BigIntegerField(null=True, blank=True)  # the line's place in the sub-account
    sub_balance = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True, default="")
    actor = models.CharField(max_length=120, default="system")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["collection"], condition=Q(outcome="routed"),
                                    name="custody_collection_routed_once"),
            models.UniqueConstraint(fields=["external_account_id", "sub_sequence"], condition=Q(outcome="routed"),
                                    name="custody_sub_sequence_unique"),
            models.CheckConstraint(
                condition=(Q(outcome="routed", routed_to_tenant__isnull=False, external_account_id__isnull=False,
                             sub_sequence__isnull=False, sub_balance__isnull=False)
                           | Q(outcome="held", routed_to_tenant__isnull=True, external_account_id__isnull=True)),
                name="custody_routing_complete"),
        ]
        indexes = [models.Index(fields=["external_account_id", "sub_sequence"])]


class PoolAlert(models.Model):
    """For WEPL operations: money on the pooled account that is held, a
    conflicting resend, or an account-level difference."""

    class Kind(models.TextChoices):
        HELD = "held", "A transaction belongs to no group yet"
        CONFLICT = "conflict", "The custodian resent a transaction with different details"
        DIFFERENCE = "difference", "The collection account and the groups' books disagree"

    tenant_scope = TenantScope.SYSTEM
    account = models.ForeignKey(CollectionAccount, on_delete=models.PROTECT, related_name="alerts")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    collection = models.ForeignKey(Collection, null=True, blank=True, on_delete=models.PROTECT)
    message = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["kind", "collection"], condition=Q(collection__isnull=False),
                                               name="custody_one_pool_alert_per_collection")]


class PoolReconciliationRun(models.Model):
    """The account-level check: the custodian's balance equals every
    sub-account's cash plus what is held."""

    tenant_scope = TenantScope.SYSTEM
    account = models.ForeignKey(CollectionAccount, on_delete=models.PROTECT, related_name="reconciliations")
    run_at = models.DateTimeField(auto_now_add=True)
    bank_balance = models.DecimalField(max_digits=18, decimal_places=2, null=True)
    books_cash = models.DecimalField(max_digits=18, decimal_places=2)
    held_net = models.DecimalField(max_digits=18, decimal_places=2)
    difference = models.DecimalField(max_digits=18, decimal_places=2, null=True)
    lines_seen = models.PositiveIntegerField()
    sub_accounts = models.PositiveIntegerField()
    sequence_gaps = models.JSONField(default=list)
    balance_breaks = models.JSONField(default=list)
    balanced = models.BooleanField()
    operation_id = models.CharField(max_length=64, blank=True, default="")
