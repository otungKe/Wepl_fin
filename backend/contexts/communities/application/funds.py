"""Use case: open one of a group's funds (ADR-0013)."""
from django.db import IntegrityError, transaction

from contexts.audit.public import record
from contexts.tenancy.public import require_tenant

from ..contract import CommunityError, FundView
from ..domain.fund import FundError, check_currency, clean_fund_name
from ..infrastructure.models import Fund
from .queries import fund_view, group_view

UNIQUE_NAME = "community_fund_name"


@transaction.atomic  # the fund and its audit event commit together, or neither does
def open_fund(group_id: int, *, name: str = "Main fund", currency: str = "KES", actor: str) -> FundView:
    """Open one of the group's named pools of money ("Main savings",
    "Welfare"). A group may have none yet, or several (ADR-0013). Balances
    are the ledger's; this only names the pool."""
    require_tenant()  # without one every group is invisible; say so, not "unknown group"
    try:
        name, currency = clean_fund_name(name), check_currency(currency)
    except FundError as exc:
        raise CommunityError(str(exc)) from None
    group = group_view(group_id)  # CommunityError for an unknown or another tenant's group
    try:
        with transaction.atomic():  # a savepoint, so a refused insert leaves the transaction usable
            fund = Fund.objects.create(group_id=group.id, name=name, currency=currency)
    except IntegrityError as exc:
        if getattr(getattr(exc.__cause__, "diag", None), "constraint_name", None) != UNIQUE_NAME:
            raise  # any other rule's refusal is not a duplicate name
        raise CommunityError(f"{group.name} already has a fund called {name!r}.") from None
    record(actor, "fund.opened", target_type="fund", target_id=fund.pk, group_id=group.id,
           data={"name": name, "currency": currency})
    return fund_view(fund.pk)
