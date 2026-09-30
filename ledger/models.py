"""The ledger records who owns what share of each group fund.

It is double-entry and append-only. The database itself enforces that every
journal entry balances, that amounts are positive and that nothing is ever
edited or deleted (migration 0002). Corrections are reversal entries.

The ledger knows groups, funds, members and external accounts only as opaque
ids. It knows nothing about banks, approvals or M-Pesa.
"""
from django.db import models
from django.db.models import Q


class Account(models.Model):
    class Purpose(models.TextChoices):
        # Money actually held at the custodian (e.g. the group's I&M account).
        CUSTODY_CASH = "custody_cash", "Cash at custodian"
        # One per member per fund: that member's share of the fund.
        MEMBER_INTEREST = "member_interest", "Member interest"
        # Money received that is not yet attributed to a member.
        UNATTRIBUTED_IN = "unattributed_in", "Unattributed receipts"
        # Money that left the account without an approved mandate.
        UNEXPLAINED_OUT = "unexplained_out", "Unexplained outflows"
        # Group-level money not owned by any one member (e.g. retained interest).
        RETAINED = "retained", "Retained by the group"

    class Side(models.TextChoices):
        DEBIT = "D", "Debit"
        CREDIT = "C", "Credit"

    NORMAL_SIDE = {
        Purpose.CUSTODY_CASH: Side.DEBIT,
        Purpose.UNEXPLAINED_OUT: Side.DEBIT,
        Purpose.MEMBER_INTEREST: Side.CREDIT,
        Purpose.UNATTRIBUTED_IN: Side.CREDIT,
        Purpose.RETAINED: Side.CREDIT,
    }

    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    group_id = models.BigIntegerField()
    fund_id = models.BigIntegerField()
    member_id = models.BigIntegerField(null=True, blank=True)
    external_account_id = models.BigIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="KES")
    normal_side = models.CharField(max_length=1, choices=Side.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["fund_id", "purpose", "member_id", "external_account_id"],
                nulls_distinct=False,
                name="ledger_account_unique_key",
            ),
            models.CheckConstraint(
                condition=Q(purpose="member_interest", member_id__isnull=False)
                | (~Q(purpose="member_interest") & Q(member_id__isnull=True)),
                name="ledger_member_interest_has_member",
            ),
            models.CheckConstraint(
                condition=Q(purpose="custody_cash", external_account_id__isnull=False)
                | (~Q(purpose="custody_cash") & Q(external_account_id__isnull=True)),
                name="ledger_custody_cash_has_external_account",
            ),
        ]

    def __str__(self):
        return f"{self.purpose} fund={self.fund_id} member={self.member_id}"


class JournalEntry(models.Model):
    idempotency_key = models.CharField(max_length=120, unique=True)
    group_id = models.BigIntegerField()
    fund_id = models.BigIntegerField()
    kind = models.CharField(max_length=40)
    memo = models.CharField(max_length=255, blank=True, default="")
    # What caused this entry, e.g. ("StatementLine", "42") or ("Mandate", "7").
    cause_type = models.CharField(max_length=60)
    cause_id = models.CharField(max_length=64)
    reverses = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversed_by"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["fund_id", "id"]),
            models.Index(fields=["cause_type", "cause_id"]),
        ]
        verbose_name_plural = "journal entries"


class JournalLine(models.Model):
    entry = models.ForeignKey(JournalEntry, on_delete=models.PROTECT, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="lines")
    side = models.CharField(max_length=1, choices=Account.Side.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="ledger_line_amount_positive"),
            models.CheckConstraint(condition=Q(side__in=["D", "C"]), name="ledger_line_side_valid"),
        ]
        indexes = [models.Index(fields=["account", "entry"])]
