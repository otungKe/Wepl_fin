from django.db import transaction

from contexts.audit.public import record
from contexts.communities.public import fund_view

from ..contract import CustodyError, ExternalAccountView
from ..infrastructure.models import ExternalAccount


def _view(ea: ExternalAccount) -> ExternalAccountView:
    return ExternalAccountView(id=ea.pk, group_id=ea.group_id, fund_id=ea.fund_id, institution=ea.institution,
                               account_number=ea.account_number, account_name=ea.account_name,
                               connector=ea.connector, currency=ea.currency)


def external_account(ea_id: int) -> ExternalAccountView:
    return _view(ExternalAccount.objects.get(pk=ea_id))


def accounts_for_group(group_id: int) -> list[ExternalAccountView]:
    return [_view(ea) for ea in ExternalAccount.objects.filter(group_id=group_id).order_by("pk")]


def all_accounts() -> list[ExternalAccountView]:
    return [_view(ea) for ea in ExternalAccount.objects.order_by("pk")]


@transaction.atomic
def link_external_account(fund_id: int, *, institution: str, account_number: str, account_name: str,
                          connector: str, actor: str) -> ExternalAccountView:
    """Record where a fund's money is held. One custodian account backs one fund."""
    fund = fund_view(fund_id)
    if ExternalAccount.objects.filter(institution=institution, account_number=account_number).exists():
        raise CustodyError(f"{institution} {account_number} is already linked.")
    ea = ExternalAccount.objects.create(group_id=fund.group_id, fund_id=fund.id, institution=institution,
                                        account_number=account_number, account_name=account_name,
                                        connector=connector, currency=fund.currency)
    record(actor, "custody.account_linked", target_type="external_account", target_id=ea.pk, group_id=fund.group_id,
           data={"institution": institution, "account_number": account_number, "connector": connector})
    return _view(ea)
