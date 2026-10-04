from django.db import IntegrityError, transaction
from django.utils import timezone

from contexts.audit.public import operation, record
from contexts.communities.public import fund_view
from contexts.shared_kernel.money import Money

from ..contract import CustodyError, ExternalAccountView
from ..domain.closing import closing_refusals
from ..domain.reconciliation import Assessment
from ..infrastructure.models import Alert, ExternalAccount
from .authority import maker_checker
from .reconciliation import reconcile


def _view(ea: ExternalAccount) -> ExternalAccountView:
    return ExternalAccountView(id=ea.pk, group_id=ea.group_id, fund_id=ea.fund_id, institution=ea.institution,
                               account_number=ea.account_number, account_name=ea.account_name,
                               connector=ea.connector, currency=ea.currency, closed_at=ea.closed_at)


def external_account(ea_id: int) -> ExternalAccountView:
    return _view(ExternalAccount.objects.get(pk=ea_id))


def accounts_for_group(group_id: int) -> list[ExternalAccountView]:
    return [_view(ea) for ea in ExternalAccount.objects.filter(group_id=group_id).order_by("pk")]


def all_accounts() -> list[ExternalAccountView]:
    return [_view(ea) for ea in ExternalAccount.objects.order_by("pk")]


@transaction.atomic
def link_external_account(fund_id: int, *, institution: str, account_number: str, account_name: str,
                          connector: str, actor: str) -> ExternalAccountView:
    """Record the group's bank account. It holds all the group's funds
    (ADR-0023); ``fund_id`` is the default fund, which takes pay-ins quoting
    no fund code, interest and charges unless the group chose otherwise, and
    outflows nobody has explained yet. The default fund cannot close while
    the account is open."""
    fund = fund_view(fund_id)
    if not fund.is_open:
        raise CustodyError(f"{fund.name} is closed.")
    if ExternalAccount.objects.filter(institution=institution, account_number=account_number).exists():
        raise CustodyError(f"{institution} {account_number} is already linked.")
    try:
        ea = ExternalAccount.objects.create(group_id=fund.group_id, fund_id=fund.id, institution=institution,
                                            account_number=account_number, account_name=account_name,
                                            connector=connector, currency=fund.currency)
    except IntegrityError as exc:  # the fund closed after it was read (custody 0004, ADR-0015)
        if getattr(getattr(exc.__cause__, "diag", None), "sqlstate", None) == "23001":
            raise CustodyError(f"{fund.name} is closed.") from None
        raise
    record(actor, "custody.account_linked", target_type="external_account", target_id=ea.pk, group_id=fund.group_id,
           data={"institution": institution, "account_number": account_number, "connector": connector})
    return _view(ea)


@transaction.atomic  # the account stays locked from the final reconciliation to the closing
def close_external_account(ea_id: int, *, by: int, confirmed_by: int) -> ExternalAccountView:
    """Record that a fund's money is no longer held at this account, so the
    fund can close (ADR-0015). Fetch the custodian's final statement first:
    closing reconciles what has been received and refuses unless the
    custodian and WEPL's books both show nothing left and nothing is still
    in question. Two members granted correct_records sign it off. A closed
    account never reopens and takes no new statement line."""
    ea = ExternalAccount.objects.select_for_update().get(pk=ea_id)
    maker, checker = maker_checker(by, confirmed_by, ea.group_id)
    if ea.closed_at is not None:
        raise CustodyError(f"{ea.institution} {ea.account_number} is already closed.")
    with operation("custody.close_account", actor=maker.msisdn):
        run = reconcile(ea.pk)
        cur = ea.currency
        assessment = Assessment(difference=Money(run.difference, cur) if run.difference is not None else None,
                                gaps=tuple(run.sequence_gaps), breaks=tuple(run.balance_breaks),
                                unresolved=run.lines_unresolved, balanced=run.balanced)
        refusals = closing_refusals(
            assessment, statement_balance=Money(run.statement_balance, cur) if run.statement_balance is not None
            else None, open_alerts=Alert.objects.filter(line__external_account=ea, resolved_at__isnull=True).count())
        if refusals:
            raise CustodyError(f"{ea.institution} {ea.account_number} cannot close: {'; '.join(refusals)}.")
        ea.closed_at = timezone.now()
        ea.save(update_fields=["closed_at"])
        record(maker.msisdn, "custody.account_closed", target_type="external_account", target_id=ea.pk,
               group_id=ea.group_id, data={"confirmed_by": checker.msisdn, "reconciliation_id": run.id})
    return _view(ea)
