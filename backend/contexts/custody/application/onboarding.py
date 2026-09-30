from django.db import transaction
from django.utils import timezone

from contexts.audit.public import operation, record
from contexts.communities.public import membership
from contexts.shared_kernel.money import Money

from ..contract import CustodyError
from ..domain import accounting
from ..domain.accounting import AccountingError
from ..domain.resolution import Outcome
from ..domain.statement import LineKind
from ..infrastructure.models import ExternalAccount, StatementLine
from . import bookkeeping as bk
from .authority import two_officials


@transaction.atomic  # the opening line, its entry and resolution are one fact
def record_opening_balances(ea_id: int, *, statement_balance, member_balances: dict, by: int,
                            confirmed_by: int) -> int | None:
    """Bring an existing account into WEPL before any other line.
    ``member_balances`` maps membership id to the amount signed off by two
    different officials, ``by`` and ``confirmed_by`` (membership ids).
    Returns the opening line's id, or None for an empty account."""
    ea = ExternalAccount.objects.select_for_update().get(pk=ea_id)
    maker, checker = two_officials(by, confirmed_by, ea.group_id)
    actor = maker.msisdn
    with operation("custody.opening_balances", actor=actor):
        balance = Money.of(statement_balance, ea.currency)
        if ea.lines.exists():
            raise CustodyError("Opening balances must be recorded before any other statement line.")
        signed_off = {}
        for mid, amt in member_balances.items():
            if membership(mid).group_id != ea.group_id:
                raise CustodyError("A signed-off member belongs to another group.")
            signed_off[mid] = Money.of(amt, ea.currency)
        if balance.is_zero:
            return None
        line = StatementLine.objects.create(
            external_account=ea, external_id="OPENING", sequence=0, posted_at=timezone.now(), kind=LineKind.OPENING,
            amount=balance.amount, running_balance=balance.amount, narration="Opening balance brought forward")
        try:
            draft = accounting.opening_balances(bk.book(ea), key=f"line:{line.pk}:opening", line_id=line.pk,
                                                statement_balance=balance, signed_off=signed_off)
        except AccountingError as exc:
            raise CustodyError(str(exc)) from None
        bk.post_and_resolve(line, draft, Outcome.OPENING, actor=actor)
        record(actor, "custody.opening_balances", target_type="external_account", target_id=ea.pk,
               group_id=ea.group_id, data={"statement_balance": str(balance.amount), "confirmed_by": checker.msisdn,
                                           "signed_off": {str(k): str(v.amount) for k, v in signed_off.items()}})
        return line.pk
