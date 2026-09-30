"""What actually happened at the custodian, and how WEPL accounted for it.

``StatementLine`` rows are facts copied from the bank and never change.
``LineResolution`` rows record how each line was accounted for; they are
append-only too, so a correction (say, attributing a payment that first went
to suspense) is a new resolution, and the full history is kept.
"""
from django.db import models
from django.db.models import Q

from governance.models import Fund, Group, Mandate, Membership


class ExternalAccount(models.Model):
    """A group's account at a custodian, e.g. an I&M Chama Account."""

    class Connector(models.TextChoices):
        IM_SIMULATOR = "im_simulator", "I&M simulator"
        CSV_UPLOAD = "csv_upload", "Statement file upload"

    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="external_accounts")
    fund = models.ForeignKey(Fund, on_delete=models.PROTECT, related_name="external_accounts")
    institution = models.CharField(max_length=40, default="I&M Bank Kenya")
    account_number = models.CharField(max_length=40)
    account_name = models.CharField(max_length=120)
    connector = models.CharField(max_length=20, choices=Connector.choices)
    currency = models.CharField(max_length=3, default="KES")
    opened_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["institution", "account_number"],
                                               name="conn_account_unique")]

    def __str__(self):
        return f"{self.institution} {self.account_number}"


class StatementLine(models.Model):
    class Kind(models.TextChoices):
        DEPOSIT = "deposit", "Deposit"
        WITHDRAWAL = "withdrawal", "Withdrawal"
        INTEREST = "interest", "Interest credit"
        CHARGE = "charge", "Bank charge"
        OPENING = "opening", "Opening balance"

    external_account = models.ForeignKey(ExternalAccount, on_delete=models.PROTECT, related_name="lines")
    bank_txn_id = models.CharField(max_length=64)
    sequence = models.BigIntegerField(help_text="The bank's order of posting, for running balances")
    posted_at = models.DateTimeField()
    kind = models.CharField(max_length=12, choices=Kind.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    narration = models.CharField(max_length=255, blank=True, default="")
    reference = models.CharField(max_length=64, blank=True, default="")
    counterparty_name = models.CharField(max_length=120, blank=True, default="")
    counterparty_msisdn = models.CharField(max_length=16, blank=True, default="")
    running_balance = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    raw = models.JSONField(default=dict, blank=True)
    ingested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["external_account", "bank_txn_id"], name="conn_line_unique"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="conn_line_amount_positive"),
        ]
        indexes = [models.Index(fields=["external_account", "sequence"])]

    @property
    def is_inflow(self):
        return self.kind in (self.Kind.DEPOSIT, self.Kind.INTEREST, self.Kind.OPENING)


class LineResolution(models.Model):
    class Outcome(models.TextChoices):
        ATTRIBUTED = "attributed", "Attributed to a member"
        UNATTRIBUTED = "unattributed", "Held as unattributed"
        INTEREST = "interest", "Interest allocated"
        CHARGE = "charge", "Bank charge allocated"
        MATCHED = "matched", "Matched to a mandate"
        UNMATCHED = "unmatched", "No mandate: alert raised"
        EXPLAINED = "explained", "Later matched to a mandate"
        OPENING = "opening", "Opening balance"

    line = models.ForeignKey(StatementLine, on_delete=models.PROTECT, related_name="resolutions")
    outcome = models.CharField(max_length=14, choices=Outcome.choices)
    membership = models.ForeignKey(Membership, null=True, blank=True, on_delete=models.PROTECT)
    mandate = models.ForeignKey(Mandate, null=True, blank=True, on_delete=models.PROTECT)
    journal_entry_id = models.BigIntegerField()
    note = models.CharField(max_length=255, blank=True, default="")
    actor = models.CharField(max_length=120, default="system")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]


class PayerMapping(models.Model):
    """Remembers who a payer is, so the treasurer is asked only once."""

    group = models.ForeignKey(Group, on_delete=models.PROTECT)
    msisdn = models.CharField(max_length=12)
    membership = models.ForeignKey(Membership, on_delete=models.PROTECT)
    confirmed_by = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["group", "msisdn"], name="conn_payer_unique")]


class Alert(models.Model):
    class Kind(models.TextChoices):
        UNMATCHED_OUTFLOW = "unmatched_outflow", "Money left without an approved mandate"
        RECONCILIATION_DIFFERENCE = "recon_difference", "Ledger and bank balance differ"
        STATEMENT_CONFLICT = "statement_conflict", "Bank sent conflicting data for a transaction"

    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="alerts")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    line = models.ForeignKey(StatementLine, null=True, blank=True, on_delete=models.PROTECT)
    message = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["kind", "line"], condition=Q(line__isnull=False),
                                    name="conn_one_alert_per_line"),
        ]


class ReconciliationRun(models.Model):
    """One comparison of WEPL's books against the custodian. Append-only."""

    external_account = models.ForeignKey(ExternalAccount, on_delete=models.PROTECT,
                                         related_name="reconciliations")
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
