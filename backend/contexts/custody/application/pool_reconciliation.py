"""The account-level check for WEPL's pooled collection account (ADR-0018)."""
from dataclasses import dataclass
from decimal import Decimal

from contexts.audit.public import current_operation_id, operation, record
from contexts.ledger.public import account_balance
from contexts.tenancy.public import cross_tenant

from ..domain.reconciliation import balance_breaks
from ..infrastructure.models import CollectionAccount, CollectionRouting, ExternalAccount, PoolAlert, PoolReconciliationRun
from . import bookkeeping as bk
from .collections import SYSTEM, CollectionResult, receive, signed


@dataclass(frozen=True)
class PoolReconciliationView:
    id: int
    bank_balance: Decimal | None
    books_cash: Decimal
    held_net: Decimal
    difference: Decimal | None
    sequence_gaps: list
    balance_breaks: list
    balanced: bool


def reconcile_pool(account_number: str) -> PoolReconciliationView:
    """The account-level check: the bank's balance equals the cash on every
    sub-account's books plus the net of held transactions, the bank's
    numbering has no gap, and its running balance follows line by line."""
    with operation("custody.reconcile_pool", actor=SYSTEM), \
            cross_tenant("custody: reconcile the pooled collection account", actor=SYSTEM):
        pool = CollectionAccount.objects.select_for_update().get(account_number=account_number)
        rows = list(pool.collections.order_by("sequence").values_list("id", "sequence", "kind", "amount",
                                                                      "running_balance"))
        routed = set(CollectionRouting.objects.filter(collection__account=pool, outcome="routed")
                     .values_list("collection_id", flat=True))
        held = sum((signed(k, a) for cid, _, k, a, _ in rows if cid not in routed), Decimal(0))
        subs = list(ExternalAccount.objects.filter(pooled_in=pool))
        books = sum((account_balance(bk.book(ea).cash()).amount for ea in subs), Decimal(0))
        balances = [b for *_, b in rows if b is not None]
        bank = balances[-1] if balances else None
        sequences = [s for _, s, *_ in rows]
        gaps = sorted(set(range(min(sequences), max(sequences) + 1)) - set(sequences)) if sequences else []
        breaks = list(balance_breaks((s, k, a, b) for _, s, k, a, b in rows))
        difference = books + held - bank if bank is not None else None
        balanced = (difference is None or difference == 0) and not gaps and not breaks
        run = PoolReconciliationRun.objects.create(
            account=pool, bank_balance=bank, books_cash=books, held_net=held, difference=difference,
            lines_seen=len(rows), sub_accounts=len(subs), sequence_gaps=gaps[:100], balance_breaks=breaks[:100],
            balanced=balanced, operation_id=current_operation_id())
        record(SYSTEM, "custody.pool_reconciled", target_type="collection_account", target_id=pool.pk,
               data={"run_id": run.pk, "balanced": balanced, "difference": str(difference)})
        if not balanced:
            PoolAlert.objects.create(account=pool, kind=PoolAlert.Kind.DIFFERENCE, message=(
                f"Pool reconciliation {run.pk}: difference {difference}, missing sequence numbers {gaps[:5]}, "
                f"running balance broken at {breaks[:5]}.")[:255])
        return PoolReconciliationView(id=run.pk, bank_balance=bank, books_cash=books, held_net=held,
                                      difference=difference, sequence_gaps=run.sequence_gaps,
                                      balance_breaks=run.balance_breaks, balanced=balanced)


def sync_collections(account_number: str, connector) -> tuple[CollectionResult, PoolReconciliationView]:
    """Fetch from the custodian, take in what is new, and reconcile the account."""
    return receive(account_number, connector.fetch(account_number)), reconcile_pool(account_number)
