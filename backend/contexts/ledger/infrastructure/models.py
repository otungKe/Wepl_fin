"""Ledger persistence. Append-only and balance-checked by PostgreSQL (0002)."""
from django.db import models
from django.db.models import Q

from contexts.tenancy.contract import TenantScope
from persistence.tenancy import tenant_column

from ..domain.accounts import AccountPurpose, Side

SIDES = [(s.value, s.name.title()) for s in Side]
DEBIT_NORMAL = [p.value for p in AccountPurpose if p.normal_side is Side.DEBIT]


class Account(models.Model):
    tenant_scope = TenantScope.TENANT_SCOPED
    tenant = tenant_column()
    purpose = models.CharField(max_length=20, choices=[(p.value, p.name) for p in AccountPurpose])
    group_id = models.BigIntegerField()
    fund_id = models.BigIntegerField()
    member_id = models.BigIntegerField(null=True, blank=True)
    external_account_id = models.BigIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="KES")
    normal_side = models.CharField(max_length=1, choices=SIDES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # The key is unique within a tenant: a row in one tenant must never
            # block another tenant's account (review of 2026-10-01, Critical 3).
            models.UniqueConstraint(fields=["tenant", "fund_id", "purpose", "member_id", "external_account_id",
                                            "currency"], nulls_distinct=False, name="ledger_account_unique_key"),
            models.CheckConstraint(condition=Q(purpose__in=[p.value for p in AccountPurpose]),
                                   name="ledger_account_purpose_known"),
            # ADR-0003's table: balances are signed by this side, so it must follow the purpose.
            models.CheckConstraint(condition=Q(purpose__in=DEBIT_NORMAL, normal_side="D")
                                   | (~Q(purpose__in=DEBIT_NORMAL) & Q(normal_side="C")),
                                   name="ledger_account_normal_side_follows_purpose"),
            models.CheckConstraint(condition=Q(currency__regex=r"^[A-Z]{3}$"), name="ledger_account_currency_code"),
            models.CheckConstraint(condition=Q(purpose="member_interest", member_id__isnull=False)
                                   | (~Q(purpose="member_interest") & Q(member_id__isnull=True)),
                                   name="ledger_member_interest_has_member"),
            models.CheckConstraint(condition=Q(purpose="custody_cash", external_account_id__isnull=False)
                                   | (~Q(purpose="custody_cash") & Q(external_account_id__isnull=True)),
                                   name="ledger_custody_cash_has_external_account"),
        ]
        # Row-level security adds "tenant = current OR cross-tenant" to every
        # query, and PostgreSQL cannot use that OR to enter an index that
        # leads with tenant. Without an index that leads with fund, every read
        # scanned every tenant's accounts (measured: ADR-0016).
        indexes = [models.Index(fields=["fund_id"], name="ledger_account_fund")]


class JournalEntry(models.Model):
    tenant_scope = TenantScope.TENANT_SCOPED
    tenant = tenant_column()
    idempotency_key = models.CharField(max_length=160)  # unique per tenant
    fingerprint = models.TextField()
    group_id = models.BigIntegerField()
    fund_id = models.BigIntegerField()
    kind = models.CharField(max_length=40)
    memo = models.CharField(max_length=255, blank=True, default="")
    cause_type = models.CharField(max_length=60)
    cause_id = models.CharField(max_length=64)
    operation_id = models.CharField(max_length=64, blank=True, default="")
    reverses = models.OneToOneField("self", null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="reversed_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["fund_id", "id"]), models.Index(fields=["cause_type", "cause_id"]),
                   # The idempotency lookup, for the reason given on Account.
                   models.Index(fields=["idempotency_key"], name="ledger_entry_key")]
        constraints = [models.UniqueConstraint(fields=["tenant", "idempotency_key"], name="ledger_entry_key_unique")]


class JournalLine(models.Model):
    tenant_scope = TenantScope.TENANT_SCOPED
    tenant = tenant_column()
    entry = models.ForeignKey(JournalEntry, on_delete=models.PROTECT, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="lines")
    side = models.CharField(max_length=1, choices=SIDES)
    amount = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="ledger_line_amount_positive"),
            models.CheckConstraint(condition=Q(side__in=["D", "C"]), name="ledger_line_side_valid"),
        ]
        indexes = [models.Index(fields=["account", "entry"])]


class IntegrityCheck(models.Model):
    """One nightly look at one fund's books (ledger 0006). Monitoring only: it
    records what the journal said at the time and is never read as a balance."""

    tenant_scope = TenantScope.TENANT_SCOPED
    tenant = tenant_column()
    fund_id = models.BigIntegerField()
    currency = models.CharField(max_length=3)
    trial_balance = models.DecimalField(max_digits=18, decimal_places=2)
    cash = models.DecimalField(max_digits=18, decimal_places=2)
    member_interests = models.DecimalField(max_digits=18, decimal_places=2)
    unattributed = models.DecimalField(max_digits=18, decimal_places=2)
    retained = models.DecimalField(max_digits=18, decimal_places=2)
    unexplained_out = models.DecimalField(max_digits=18, decimal_places=2)
    invariant_holds = models.BooleanField()
    passed = models.BooleanField()
    lines = models.PositiveBigIntegerField()  # the fund's history: what ADR-0016's threshold watches
    # Fund-transfer entries of this fund whose other half is missing (ADR-0024).
    # PostgreSQL refuses such a commit (ledger 0009); this watches for a bypass.
    unpaired_transfers = models.PositiveIntegerField(default=0)
    checked_at = models.DateTimeField(auto_now_add=True)
    operation_id = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["fund_id", "id"])]
        constraints = [models.CheckConstraint(  # "passed" can only mean every check held
            condition=Q(passed=True, trial_balance=0, invariant_holds=True, unpaired_transfers=0)
            | (Q(passed=False) & ~Q(trial_balance=0, invariant_holds=True, unpaired_transfers=0)),
            name="ledger_check_passed_means_all")]
