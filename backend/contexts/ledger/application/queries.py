"""Balances are always derived from journal lines, never stored."""
from decimal import Decimal

from django.db.models import Case, DecimalField, F, Sum, Value, When

from contexts.shared_kernel.money import Money

from ..domain.accounts import AccountKey, AccountPurpose, Side
from ..domain.journal import LedgerError
from ..domain.position import FundPosition
from ..infrastructure import accounts
from ..infrastructure.models import JournalEntry, JournalLine

_DEC = DecimalField(max_digits=18, decimal_places=2)
_SIGNED = Sum(Case(When(side=F("account__normal_side"), then=F("amount")), default=-F("amount"), output_field=_DEC))


def account_balance(key: AccountKey) -> Money:
    acct = accounts.find(key)
    total = JournalLine.objects.filter(account=acct).aggregate(v=_SIGNED)["v"] if acct else None
    return Money(total or 0, key.currency)


def cash_by_fund(external_account_id: int, currency: str = "KES") -> dict[int, Money]:
    """What each fund holds at one custodian account. A group's funds may
    share its one bank account (ADR-0023); the account's balance is the sum."""
    rows = (JournalLine.objects.filter(account__external_account_id=external_account_id,
                                       account__purpose=AccountPurpose.CUSTODY_CASH, account__currency=currency)
            .values("account__fund_id").annotate(v=_SIGNED))
    return {r["account__fund_id"]: Money(r["v"] or 0, currency) for r in rows}


def entry_fund(entry_id: int) -> int:
    """The fund whose books a journal entry is in."""
    fund_id = JournalEntry.objects.filter(pk=entry_id).values_list("fund_id", flat=True).first()
    if fund_id is None:  # unknown, or another tenant's (row-level security hides it)
        raise LedgerError(f"Unknown journal entry {entry_id}.")
    return fund_id


def entry_funds(entry_ids) -> dict[int, int]:
    """The fund of each journal entry named."""
    return dict(JournalEntry.objects.filter(pk__in=list(entry_ids)).values_list("pk", "fund_id"))


def entry_credits(entry_id: int) -> list[tuple[AccountKey, Money]]:
    """The accounts a journal entry credits, and by how much."""
    rows = JournalLine.objects.filter(entry_id=entry_id, side=Side.CREDIT.value).select_related("account").order_by("id")
    return [(AccountKey(group_id=r.account.group_id, fund_id=r.account.fund_id, purpose=r.account.purpose,
                        member_id=r.account.member_id, external_account_id=r.account.external_account_id,
                        currency=r.account.currency), Money(r.amount, r.account.currency)) for r in rows]


def member_balances(fund_id: int, currency: str = "KES") -> dict[int, Money]:
    rows = (JournalLine.objects.filter(account__fund_id=fund_id, account__purpose=AccountPurpose.MEMBER_INTEREST,
                                       account__currency=currency)
            .values("account__member_id").annotate(v=_SIGNED))
    return {r["account__member_id"]: Money(r["v"] or 0, currency) for r in rows}


def fund_position(fund_id: int, currency: str = "KES") -> FundPosition:
    rows = (JournalLine.objects.filter(account__fund_id=fund_id, account__currency=currency)
            .values("account__purpose").annotate(v=_SIGNED))
    by = {r["account__purpose"]: Money(r["v"] or 0, currency) for r in rows}
    get = lambda p: by.get(p.value, Money.zero(currency))
    return FundPosition(cash=get(AccountPurpose.CUSTODY_CASH), member_interests=get(AccountPurpose.MEMBER_INTEREST),
                        unattributed=get(AccountPurpose.UNATTRIBUTED_IN), retained=get(AccountPurpose.RETAINED),
                        unexplained_out=get(AccountPurpose.UNEXPLAINED_OUT))


def fund_holds_nothing(fund_id: int) -> bool:
    """Whether every account of the fund, in every currency, is at zero:
    no member, the group or the custodian holds anything in it."""
    return not (JournalLine.objects.filter(account__fund_id=fund_id).values("account_id")
                .annotate(v=_SIGNED).exclude(v=0).exists())


def trial_balance(fund_id: int | None = None, currency: str = "KES") -> Decimal:
    """Total debits minus total credits in one currency: zero whenever the
    ledger is sound. Never summed across currencies, where a surplus in one
    could hide a shortfall in another."""
    qs = JournalLine.objects.filter(account__currency=currency)
    qs = qs if fund_id is None else qs.filter(account__fund_id=fund_id)
    agg = qs.aggregate(
        d=Sum(Case(When(side=Side.DEBIT.value, then=F("amount")), default=Value(0), output_field=_DEC)),
        c=Sum(Case(When(side=Side.CREDIT.value, then=F("amount")), default=Value(0), output_field=_DEC)))
    return (agg["d"] or Decimal(0)) - (agg["c"] or Decimal(0))


def member_movements(fund_id: int, member_id: int, currency: str = "KES") -> list[dict]:
    """One member's movements in a fund and currency, in posting order (entry
    id, which follows insertion), with a running balance."""
    rows = (JournalLine.objects.filter(account__fund_id=fund_id, account__purpose=AccountPurpose.MEMBER_INTEREST,
                                       account__member_id=member_id, account__currency=currency)
            .select_related("entry", "account").order_by("entry_id", "id"))
    running, out = Decimal("0.00"), []
    for r in rows:
        credit = r.side == Side.CREDIT.value
        running += r.amount if credit else -r.amount
        out.append({"entry_id": r.entry_id, "date": r.entry.created_at, "kind": r.entry.kind, "memo": r.entry.memo,
                    "in": r.amount if credit else None, "out": None if credit else r.amount, "balance": running})
    return out
