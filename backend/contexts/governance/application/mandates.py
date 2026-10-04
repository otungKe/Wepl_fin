"""Mandate state changes and lookups."""
from django.utils import timezone

from contexts.audit.public import record
from contexts.shared_kernel.money import Money

from ..contract import MandateView
from ..domain.lifecycle import MANDATE_TRANSITIONS, MandateStatus, ensure
from ..domain.mandate import Allocation
from ..infrastructure.models import Mandate


def _view(m: Mandate) -> MandateView:
    return MandateView(id=m.pk, group_id=m.group_id, fund_id=m.fund_id, reference=m.reference,
                       amount=Money(m.amount, m.currency), payee_name=m.payee_name, payee_account=m.payee_account,
                       allocation=Allocation(m.allocation), charged_member_id=m.charged_member_id,
                       status=MandateStatus(m.status), expires_at=m.expires_at)


def mandate(mandate_id: int) -> MandateView:
    return _view(Mandate.objects.get(pk=mandate_id))


def find_by_reference(fund_id: int, references) -> MandateView | None:
    m = Mandate.objects.filter(fund_id=fund_id, reference__in=list(references)).order_by("id").first()
    return _view(m) if m else None


def mandates_by_reference(references) -> list[MandateView]:
    """Mandates quoting any of ``references``, in any fund the caller can
    see. References are unique across WEPL, so in a declared cross-tenant
    operation this finds the one group a pooled payout belongs to (ADR-0018)."""
    return [_view(m) for m in Mandate.objects.filter(reference__in=list(references)).order_by("id")]


def issued_for_amount(fund_id: int, amount: Money) -> list[MandateView]:
    return [_view(m) for m in Mandate.objects.filter(fund_id=fund_id, status=MandateStatus.ISSUED,
                                                     amount=amount.amount, currency=amount.currency).order_by("id")]


def execute_mandate(mandate_id: int, *, line_id: int, when) -> bool:
    """Mark an issued mandate executed by a custody statement line. Returns
    False if it is no longer issued. A conditional UPDATE makes this safe when
    two workers see the same outflow: exactly one wins."""
    ensure(MANDATE_TRANSITIONS, MandateStatus.ISSUED, MandateStatus.EXECUTED)
    won = Mandate.objects.filter(pk=mandate_id, status=MandateStatus.ISSUED).update(
        status=MandateStatus.EXECUTED, executed_at=when, executed_by_line_id=line_id) == 1
    if won:
        m = Mandate.objects.get(pk=mandate_id)
        record("system", "mandate.executed", target_type="mandate", target_id=m.pk, group_id=m.group_id,
               data={"line_id": line_id})
    return won


def expire_mandates(now=None) -> int:
    ensure(MANDATE_TRANSITIONS, MandateStatus.ISSUED, MandateStatus.EXPIRED)
    now = now or timezone.now()
    due = list(Mandate.objects.filter(status=MandateStatus.ISSUED, expires_at__lt=now).values_list("pk", "group_id"))
    for pk, group_id in due:
        if Mandate.objects.filter(pk=pk, status=MandateStatus.ISSUED).update(status=MandateStatus.EXPIRED):
            record("system", "mandate.expired", target_type="mandate", target_id=pk, group_id=group_id)
    return len(due)
