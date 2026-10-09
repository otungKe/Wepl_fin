"""The nightly look at the books: monitoring, never a source of balances.

PostgreSQL already refuses an unbalanced entry (0002, 0005), so a failure here
means one of those rules was bypassed (a superuser, a restore, a bug in a
trigger). The check records what it saw and raises the alarm; it never
corrects anything. Corrections stay reversals, decided by people.

It reads the journal with its own SQL (``infrastructure/books.py``), so it
does not trust the balance queries it is meant to watch: it re-checks every
entry, not only the fund's net, and fails a fund whose balance queries
disagree with its own sums."""
from decimal import Decimal

from contexts.audit.public import current_operation_id, operation, record
from contexts.notifications.public import notify
from contexts.shared_kernel.money import Money

from ..domain.accounts import AccountPurpose, Side
from ..domain.position import FundPosition
from ..infrastructure import books
from ..infrastructure.models import Account, IntegrityCheck
from .queries import fund_position, trial_balance


def check_books(*, actor: str = "system") -> list[IntegrityCheck]:
    """Check every fund of the current tenant that has books, in each
    currency: the trial balance is zero, cash equals what the fund owes plus
    what it retains, every entry obeys the posting rules on its own, every
    fund-transfer entry has its other half in another fund (ADR-0024), and
    the balance queries agree with the check's own sums. Records one row per
    fund and currency, with the line count (the measure ADR-0016's threshold
    watches), and alerts on each failure."""
    with operation("ledger.integrity_check", actor=actor):
        funds = Account.objects.values_list("fund_id", "currency").distinct().order_by("fund_id", "currency")
        per_fund: dict[int, tuple[int, int]] = {}
        checks = []
        for fund_id, currency in funds:
            if fund_id not in per_fund:
                per_fund[fund_id] = books.broken_entries(fund_id), books.unpaired_transfers(fund_id)
            checks.append(_check(fund_id, currency, *per_fund[fund_id]))
        for c in checks:
            if not c.passed:
                group_id = Account.objects.filter(fund_id=c.fund_id).values_list("group_id", flat=True).first()
                record(actor, "ledger.integrity_check_failed", target_type="fund", target_id=c.fund_id,
                       group_id=group_id, data={"check_id": c.pk, "currency": c.currency, "trial_balance": str(c.trial_balance),
                             "invariant_holds": c.invariant_holds, "unpaired_transfers": c.unpaired_transfers,
                             "broken_entries": c.broken_entries, "queries_agree": c.queries_agree})
                notify("ops.ledger_integrity_failure", {"check_id": c.pk, "fund_id": c.fund_id},
                       dedupe_key=f"ops.ledger_integrity_failure:{c.pk}")
        return checks


def latest_checks() -> list[dict]:
    """The most recent check of each fund's books in the current tenant."""
    return list(IntegrityCheck.objects.order_by("fund_id", "currency", "-id").distinct("fund_id", "currency")
                .values("fund_id", "currency", "passed", "checked_at"))


def _check(fund_id: int, currency: str, broken: int, unpaired: int) -> IntegrityCheck:
    by_purpose, lines = books.totals_by_purpose(fund_id, currency)
    debits = sum((d for d, _ in by_purpose.values()), Decimal(0))
    credits = sum((c for _, c in by_purpose.values()), Decimal(0))

    def held(purpose: AccountPurpose) -> Money:  # signed by the purpose's normal side, as ADR-0003 defines it
        d, c = by_purpose.get(purpose.value, (0, 0))
        return Money((d - c) if purpose.normal_side is Side.DEBIT else (c - d), currency)

    pos = FundPosition(cash=held(AccountPurpose.CUSTODY_CASH), member_interests=held(AccountPurpose.MEMBER_INTEREST),
                       unattributed=held(AccountPurpose.UNATTRIBUTED_IN), retained=held(AccountPurpose.RETAINED),
                       unexplained_out=held(AccountPurpose.UNEXPLAINED_OUT))
    tb = debits - credits
    agree = fund_position(fund_id, currency) == pos and trial_balance(fund_id, currency) == tb
    return IntegrityCheck.objects.create(
        fund_id=fund_id, currency=currency, trial_balance=tb, cash=pos.cash.amount,
        member_interests=pos.member_interests.amount, unattributed=pos.unattributed.amount,
        retained=pos.retained.amount, unexplained_out=pos.unexplained_out.amount,
        invariant_holds=pos.invariant_holds, unpaired_transfers=unpaired, broken_entries=broken, queries_agree=agree,
        passed=tb == 0 and pos.invariant_holds and unpaired == 0 and broken == 0 and agree,
        lines=lines, operation_id=current_operation_id())
