"""The nightly look at the books: monitoring, never a source of balances.

PostgreSQL already refuses an unbalanced entry (0002, 0005), so a failure here
means one of those rules was bypassed (a superuser, a restore, a bug in a
trigger). The check records what it saw and raises the alarm; it never
corrects anything. Corrections stay reversals, decided by people."""
from contexts.audit.public import current_operation_id, operation, record
from contexts.notifications.public import notify

from ..infrastructure.models import Account, IntegrityCheck, JournalLine
from .queries import fund_position, trial_balance


def check_books(*, actor: str = "system") -> list[IntegrityCheck]:
    """Check every fund of the current tenant that has books: the trial
    balance is zero and cash equals what the fund owes plus what it retains.
    Records one row per fund and currency, with the fund's line count (the
    measure ADR-0016's threshold watches), and alerts on each failure."""
    with operation("ledger.integrity_check", actor=actor):
        books = Account.objects.values_list("fund_id", "currency").distinct().order_by("fund_id", "currency")
        checks = [_check(fund_id, currency) for fund_id, currency in books]
        for c in checks:
            if not c.passed:
                group_id = Account.objects.filter(fund_id=c.fund_id).values_list("group_id", flat=True).first()
                record(actor, "ledger.integrity_check_failed", target_type="fund", target_id=c.fund_id,
                       group_id=group_id, data={"check_id": c.pk, "currency": c.currency, "trial_balance": str(c.trial_balance),
                             "invariant_holds": c.invariant_holds})
                notify("ops.ledger_integrity_failure", {"check_id": c.pk, "fund_id": c.fund_id},
                       dedupe_key=f"ops.ledger_integrity_failure:{c.pk}")
        return checks


def latest_checks() -> list[dict]:
    """The most recent check of each fund's books in the current tenant."""
    return list(IntegrityCheck.objects.order_by("fund_id", "currency", "-id").distinct("fund_id", "currency")
                .values("fund_id", "currency", "passed", "checked_at"))


def _check(fund_id: int, currency: str) -> IntegrityCheck:
    tb, pos = trial_balance(fund_id), fund_position(fund_id, currency)
    return IntegrityCheck.objects.create(
        fund_id=fund_id, currency=currency, trial_balance=tb, cash=pos.cash.amount,
        member_interests=pos.member_interests.amount, unattributed=pos.unattributed.amount,
        retained=pos.retained.amount, unexplained_out=pos.unexplained_out.amount,
        invariant_holds=pos.invariant_holds, passed=tb == 0 and pos.invariant_holds,
        lines=JournalLine.objects.filter(account__fund_id=fund_id, account__currency=currency).count(),
        operation_id=current_operation_id())
