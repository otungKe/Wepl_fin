from django.db import transaction

from contexts.audit.public import current_operation_id, operation, record
from contexts.ledger.public import account_balance, fund_position
from contexts.notifications.public import notify
from contexts.shared_kernel.money import Money

from ..contract import IngestResult, ReconciliationView
from ..domain.reconciliation import assess, balance_breaks
from ..domain.statement import Connector, LineKind
from ..infrastructure.models import Alert, ExternalAccount, ReconciliationRun
from . import bookkeeping as bk
from .ingestion import ingest


def _view(r: ReconciliationRun) -> ReconciliationView:
    return ReconciliationView(
        id=r.pk, statement_balance=r.statement_balance, ledger_cash=r.ledger_cash, difference=r.difference,
        member_interests=r.member_interests, unattributed=r.unattributed, unexplained_out=r.unexplained_out,
        retained=r.retained, lines_seen=r.lines_seen, lines_unresolved=r.lines_unresolved,
        sequence_gaps=r.sequence_gaps, balance_breaks=r.balance_breaks, open_alerts=r.open_alerts, balanced=r.balanced)


@transaction.atomic  # the account lock gives a consistent snapshot of lines and books
def reconcile(ea_id: int) -> ReconciliationView:
    """Compare WEPL's books with the custodian's statement and record the result."""
    with operation("custody.reconcile", actor="system"):
        ea = ExternalAccount.objects.select_for_update().get(pk=ea_id)
        lines = ea.lines.order_by("sequence")
        last = lines.exclude(running_balance__isnull=True).last()
        cur = ea.currency
        a = assess(statement_balance=Money(last.running_balance, cur) if last else None,
                   ledger_cash=account_balance(bk.book(ea).cash()),
                   sequences=list(lines.exclude(kind=LineKind.OPENING).values_list("sequence", flat=True)),
                   unresolved=lines.filter(resolutions__isnull=True).count(),
                   breaks=balance_breaks(lines.values_list("sequence", "kind", "amount", "running_balance")))
        pos = fund_position(ea.fund_id, cur)
        run = ReconciliationRun.objects.create(
            external_account=ea, statement_balance=last.running_balance if last else None,
            ledger_cash=pos.cash.amount, difference=a.difference.amount if a.difference else None,
            member_interests=pos.member_interests.amount, unattributed=pos.unattributed.amount,
            unexplained_out=pos.unexplained_out.amount, retained=pos.retained.amount, lines_seen=lines.count(),
            lines_unresolved=a.unresolved, sequence_gaps=list(a.gaps[:100]), balance_breaks=list(a.breaks[:100]),
            open_alerts=Alert.objects.filter(group_id=ea.group_id, resolved_at__isnull=True).count(),
            balanced=a.balanced, operation_id=current_operation_id())
        record("system", "custody.reconciled", target_type="external_account", target_id=ea.pk, group_id=ea.group_id,
               data={"run_id": run.pk, "balanced": a.balanced, "difference": str(run.difference)})
        if not a.balanced:
            alert = Alert.objects.create(
                group_id=ea.group_id, kind=Alert.Kind.RECONCILIATION_DIFFERENCE,
                message=(f"Reconciliation {run.pk}: difference {run.difference}, missing sequence numbers "
                         f"{list(a.gaps[:5])}, running balance broken at {list(a.breaks[:5])}, "
                         f"unaccounted lines {a.unresolved}.")[:255])
            notify("ops.reconciliation_difference", {"run_id": run.pk, "alert_id": alert.pk},
                   dedupe_key=f"ops.reconciliation_difference:{run.pk}")
        return _view(run)


def sync(ea_id: int, connector: Connector) -> tuple[IngestResult, ReconciliationView]:
    """Fetch from the custodian, take in what is new, and reconcile."""
    ea = ExternalAccount.objects.get(pk=ea_id)
    with operation("custody.sync", actor="system"):
        result = ingest(ea.pk, connector.fetch(ea.account_number))
        return result, reconcile(ea.pk)


def latest_reconciliation(ea_id: int) -> ReconciliationView | None:
    r = ReconciliationRun.objects.filter(external_account_id=ea_id).order_by("-id").first()
    return _view(r) if r else None
