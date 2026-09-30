"""Use case: open one of a group's funds (ADR-0013)."""
from django.db import IntegrityError, transaction

from contexts.audit.public import record

from ..contract import CommunityError, FundView
from ..infrastructure.models import Fund
from .queries import fund_view, group_view


@transaction.atomic
def open_fund(group_id: int, *, name: str = "Main fund", currency: str = "KES", actor: str) -> FundView:
    """Open one of the group's named pools of money ("Main savings",
    "Welfare"). A group may have none yet, or several (ADR-0013). Balances
    are the ledger's; this only names the pool."""
    group = group_view(group_id)  # CommunityError for an unknown or another tenant's group
    name = name.strip()
    if not name:
        raise CommunityError("A fund needs a name.")
    try:
        with transaction.atomic():
            fund = Fund.objects.create(group_id=group.id, name=name, currency=currency)
    except IntegrityError:
        raise CommunityError(f"{group.name} already has a fund called {name!r}.") from None
    record(actor, "fund.opened", target_type="fund", target_id=fund.pk, group_id=group.id,
           data={"name": name, "currency": currency})
    return fund_view(fund.pk)
