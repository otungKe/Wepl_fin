"""Use cases for a group's funds: open, rename, code, close (ADR-0013; lifecycle
decided by Harry, 2026-10-01, ADR-0015; codes ADR-0023)."""
from django.db import IntegrityError, transaction

from contexts.audit.public import record
from contexts.ledger.public import fund_holds_nothing
from contexts.tenancy.public import require_tenant

from ..contract import CommunityError, FundView
from ..domain.fund import FundError, FundStatus, check_currency, clean_fund_code, clean_fund_name, ensure_open
from ..infrastructure.models import Fund
from .queries import fund_view, group_view

UNIQUE_NAME = "community_open_fund_name_any_case"
UNIQUE_CODE = "community_open_fund_code"


def _domain(fn, *args):
    try:
        return fn(*args)
    except FundError as exc:
        raise CommunityError(str(exc)) from None


def _save_name(save, group_name: str, name: str, code: str | None = None):
    """Run ``save`` in a savepoint; only the open-fund name and code indexes'
    refusals mean a duplicate. Any other rule's refusal propagates as it is."""
    try:
        with transaction.atomic():  # a savepoint, so a refused write leaves the transaction usable
            return save()
    except IntegrityError as exc:
        constraint = getattr(getattr(exc.__cause__, "diag", None), "constraint_name", None)
        if constraint == UNIQUE_CODE:
            raise CommunityError(f"Another open fund of {group_name} already has the code {code}.") from None
        if constraint != UNIQUE_NAME:
            raise
        raise CommunityError(f"{group_name} already has a fund called {name!r}.") from None


def _locked(fund_id: int) -> Fund:
    f = Fund.objects.select_for_update().filter(pk=fund_id).first()
    if f is None:  # unknown, or another tenant's and so invisible
        raise CommunityError(f"Unknown fund {fund_id}.")
    return f


def hold_open_fund(fund_id: int) -> FundView:
    """The fund, locked against closing until the caller's transaction ends.
    For another context about to post money into it: closing takes the same
    lock and then finds the money, so the two cannot cross. Refuses a closed
    fund. Call inside a transaction."""
    f = _locked(fund_id)
    _domain(ensure_open, f.status)
    return fund_view(f.pk)


@transaction.atomic  # the fund and its audit event commit together, or neither does
def open_fund(group_id: int, *, name: str, currency: str = "KES", code: str | None = None,
              actor: str) -> FundView:
    """Open one of the group's named pools of money ("Main savings",
    "Welfare"). A group may have none yet, or several (ADR-0013). Balances
    are the ledger's; this only names the pool. The name is the group's own,
    from its constitution (§3); there is no default. ``code`` is what members
    add to a pay-in reference to pay into this fund (ADR-0023)."""
    require_tenant()  # without one every group is invisible; say so, not "unknown group"
    name, currency = _domain(clean_fund_name, name), _domain(check_currency, currency)
    code = _domain(clean_fund_code, code) if code is not None else None
    group = group_view(group_id)  # CommunityError for an unknown or another tenant's group
    fund = _save_name(lambda: Fund.objects.create(group_id=group.id, name=name, currency=currency, code=code),
                      group.name, name, code)
    record(actor, "fund.opened", target_type="fund", target_id=fund.pk, group_id=group.id,
           data={"name": name, "currency": currency, **({"code": code} if code else {})})
    return fund_view(fund.pk)


@transaction.atomic
def rename_fund(fund_id: int, name: str, *, actor: str) -> FundView:
    """Rename an open fund. Records refer to the fund by id, so nothing
    breaks; the audit trail keeps every earlier name. The name is the
    constitution's (§3), so who may rename follows who may change it."""
    require_tenant()
    f = _locked(fund_id)
    _domain(ensure_open, f.status)
    name = _domain(clean_fund_name, name)
    if name != f.name:
        old, f.name = f.name, name
        _save_name(lambda: f.save(update_fields=["name"]), group_view(f.group_id).name, name)
        record(actor, "fund.renamed", target_type="fund", target_id=f.pk, group_id=f.group_id,
               data={"from": old, "to": name})
    return fund_view(f.pk)


@transaction.atomic
def set_fund_code(fund_id: int, code: str, *, actor: str) -> FundView:
    """Give an open fund the code members add to a pay-in reference to pay
    into it (ADR-0023), or change it. Members must be told: a pay-in quoting
    the old code goes to the group's default fund."""
    require_tenant()
    f = _locked(fund_id)
    _domain(ensure_open, f.status)
    code = _domain(clean_fund_code, code)
    if code != f.code:
        old, f.code = f.code, code
        _save_name(lambda: f.save(update_fields=["code"]), group_view(f.group_id).name, f.name, code)
        record(actor, "fund.code_set", target_type="fund", target_id=f.pk, group_id=f.group_id,
               data={"from": old, "to": code})
    return fund_view(f.pk)


@transaction.atomic
def close_fund(fund_id: int, *, actor: str) -> FundView:
    """Close a fund that is empty. Final: a group that needs the pool again
    opens a new fund. Each context refuses what is its own to refuse:
    - the ledger: anything still held in the fund (checked here, through its
      public query, under the fund's row lock);
    - governance: an open proposal or an unexecuted mandate (its database
      trigger, governance 0005);
    - custody: a linked custodian account (its database trigger, custody 0004).
    A closed fund then takes no new proposal, account or name."""
    require_tenant()
    f = _locked(fund_id)
    _domain(ensure_open, f.status)
    if not fund_holds_nothing(f.pk):
        raise CommunityError(f"{f.name} still holds money; it can close only when everything is paid out.")
    f.status = FundStatus.CLOSED
    try:
        with transaction.atomic():
            f.save(update_fields=["status"])
    except IntegrityError as exc:  # governance's or custody's refusal (restrict_violation), in its own words
        diag = getattr(exc.__cause__, "diag", None)
        if getattr(diag, "sqlstate", None) != "23001":
            raise
        raise CommunityError(f"{f.name} cannot close: {diag.message_primary}.") from None
    record(actor, "fund.closed", target_type="fund", target_id=f.pk, group_id=f.group_id, data={"name": f.name})
    return fund_view(f.pk)
