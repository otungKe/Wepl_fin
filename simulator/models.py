"""A stand-in for I&M Bank used in tests and demos, never in production.

It keeps its own books, independent of WEPL's ledger, so reconciliation
compares two genuinely separate records, as it will against the real bank."""
from django.db import models


class SimAccount(models.Model):
    number = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    balance = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    next_sequence = models.BigIntegerField(default=1)


class SimTransaction(models.Model):
    account = models.ForeignKey(SimAccount, on_delete=models.CASCADE, related_name="txns")
    txn_id = models.CharField(max_length=64, unique=True)
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
        ordering = ["account", "sequence"]
        constraints = [models.UniqueConstraint(fields=["account", "sequence"], name="sim_seq_unique")]
