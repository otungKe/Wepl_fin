from django.db import models

from contexts.tenancy.contract import TenantScope


class SimAccount(models.Model):
    tenant_scope = TenantScope.GLOBAL  # a stand-in for the bank's own system, not WEPL data
    number = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    balance = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    next_sequence = models.BigIntegerField(default=1)


class SimTransaction(models.Model):
    tenant_scope = TenantScope.GLOBAL
    account = models.ForeignKey(SimAccount, on_delete=models.PROTECT, related_name="transactions")
    txn_id = models.CharField(max_length=32, unique=True)
    sequence = models.BigIntegerField()
    posted_at = models.DateTimeField()
    kind = models.CharField(max_length=12)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    narration = models.CharField(max_length=255, blank=True, default="")
    reference = models.CharField(max_length=64, blank=True, default="")
    counterparty_name = models.CharField(max_length=120, blank=True, default="")
    counterparty_msisdn = models.CharField(max_length=16, blank=True, default="")
    balance_after = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["account", "sequence"], name="sim_sequence_unique")]
        ordering = ["account", "sequence"]
