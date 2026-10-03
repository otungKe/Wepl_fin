"""Custody persistence.

Statement lines are facts copied from the custodian and never change; line
resolutions record how each was accounted for and are append-only too, so a
correction is a new resolution and the full history is kept (0002).

Cross-context references (ADR-0004): group and fund (communities), the member
a payment was attributed to (communities) and the mandate a payout executed
(governance) are deliberate foreign keys; none of those rows is ever deleted.
"""
from django.db import models
from django.db.models import Q

from contexts.tenancy.contract import TenantScope
from persistence.tenancy import tenant_column

from ..domain.resolution import Outcome
from ..domain.statement import LineKind

GROUP, FUND, MEMBERSHIP, MANDATE = "communities.Group", "communities.Fund", "communities.Membership", "governance.Mandate"


class ExternalAccount(models.Model):
    """A group's account at a custodian, e.g. a Chama Account at the custodian bank."""

    tenant_scope = TenantScope.TENANT_SCOPED
    tenant = tenant_column()
    group = models.ForeignKey(GROUP, on_delete=models.PROTECT, related_name="+")
    fund = models.ForeignKey(FUND, on_delete=models.PROTECT, related_name="+")
    institution = models.CharField(max_length=40)
    account_number = models.CharField(max_length=40)
    account_name = models.CharField(max_length=120)
    connector = models.CharField(max_length=40)
    currency = models.CharField(max_length=3, default="KES")
    linked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["institution", "account_number"], name="custody_account_unique")]


class StatementLine(models.Model):
    tenant_scope = TenantScope.TENANT_SCOPED
    tenant = tenant_column()
    external_account = models.ForeignKey(ExternalAccount, on_delete=models.PROTECT, related_name="lines")
    external_id = models.CharField(max_length=64, help_text="The custodian's transaction id")
    sequence = models.BigIntegerField(help_text="The custodian's posting order")
    posted_at = models.DateTimeField()
    kind = models.CharField(max_length=12, choices=[(k.value, k.value) for k in LineKind])
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    narration = models.CharField(max_length=255, blank=True, default="")
    reference = models.CharField(max_length=64, blank=True, default="")
    counterparty_name = models.CharField(max_length=120, blank=True, default="")
    counterparty_msisdn = models.CharField(max_length=16, blank=True, default="")
    running_balance = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ingested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["external_account", "external_id"], name="custody_line_unique"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="custody_line_amount_positive"),
        ]
        indexes = [models.Index(fields=["external_account", "sequence"])]


class LineResolution(models.Model):
    tenant_scope = TenantScope.TENANT_SCOPED
    tenant = tenant_column()
    line = models.ForeignKey(StatementLine, on_delete=models.PROTECT, related_name="resolutions")
    outcome = models.CharField(max_length=14, choices=[(o.value, o.value) for o in Outcome])
    membership = models.ForeignKey(MEMBERSHIP, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    mandate = models.ForeignKey(MANDATE, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    journal_entry_id = models.BigIntegerField()
    note = models.CharField(max_length=255, blank=True, default="")
    actor = models.CharField(max_length=120, default="system")
    created_at = models.DateTimeField(auto_now_add=True)


class PayerMapping(models.Model):
    """Remembers who a payer is, so nobody is asked twice."""

    tenant_scope = TenantScope.TENANT_SCOPED
    tenant = tenant_column()
    group = models.ForeignKey(GROUP, on_delete=models.PROTECT, related_name="+")
    msisdn = models.CharField(max_length=12)
    membership = models.ForeignKey(MEMBERSHIP, on_delete=models.PROTECT, related_name="+")
    confirmed_by = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["group", "msisdn"], name="custody_payer_unique")]


class Alert(models.Model):
    tenant_scope = TenantScope.TENANT_SCOPED
    tenant = tenant_column()
    class Kind(models.TextChoices):
        UNMATCHED_OUTFLOW = "unmatched_outflow", "Money left without an approved mandate"
        RECONCILIATION_DIFFERENCE = "recon_difference", "Books and custodian disagree"
        STATEMENT_CONFLICT = "statement_conflict", "Custodian sent conflicting data for a transaction"

    group = models.ForeignKey(GROUP, on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    line = models.ForeignKey(StatementLine, null=True, blank=True, on_delete=models.PROTECT)
    message = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["kind", "line"], condition=Q(line__isnull=False),
                                               name="custody_one_alert_per_line")]


class ReconciliationRun(models.Model):
    tenant_scope = TenantScope.TENANT_SCOPED
    tenant = tenant_column()
    external_account = models.ForeignKey(ExternalAccount, on_delete=models.PROTECT, related_name="reconciliations")
    run_at = models.DateTimeField(auto_now_add=True)
    statement_balance = models.DecimalField(max_digits=18, decimal_places=2, null=True)
    ledger_cash = models.DecimalField(max_digits=18, decimal_places=2)
    difference = models.DecimalField(max_digits=18, decimal_places=2, null=True)
    member_interests = models.DecimalField(max_digits=18, decimal_places=2)
    unattributed = models.DecimalField(max_digits=18, decimal_places=2)
    unexplained_out = models.DecimalField(max_digits=18, decimal_places=2)
    retained = models.DecimalField(max_digits=18, decimal_places=2)
    lines_seen = models.PositiveIntegerField()
    lines_unresolved = models.PositiveIntegerField()
    sequence_gaps = models.JSONField(default=list)
    open_alerts = models.PositiveIntegerField()
    balanced = models.BooleanField()
    operation_id = models.CharField(max_length=64, blank=True, default="")
