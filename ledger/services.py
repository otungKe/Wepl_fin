"""The only way to write to the ledger. Nothing else creates journal rows."""
from dataclasses import dataclass
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Case, DecimalField, F, Sum, Value, When

from wepl.money import to_money

from .models import Account, JournalEntry, JournalLine

D, C = Account.Side.DEBIT, Account.Side.CREDIT
Purpose = Account.Purpose


class LedgerError(Exception):
    pass


@dataclass(frozen=True)
class Line:
    account: Account
    side: str
    amount: Decimal


def account(purpose: str, *, group_id: int, fund_id: int, member_id: int | None = None,
            external_account_id: int | None = None, currency: str = "KES") -> Account:
    """Get or create the account for a key. Safe under concurrency."""
    key = dict(purpose=purpose, fund_id=fund_id, member_id=member_id,
               external_account_id=external_account_id)
    found = Account.objects.filter(**key).first()
    if found:
        return found
    try:
        with transaction.atomic():
            return Account.objects.create(
                group_id=group_id, currency=currency,
                normal_side=Account.NORMAL_SIDE[purpose], **key,
            )
    except IntegrityError:
        return Account.objects.get(**key)


def post(*, idempotency_key: str, group_id: int, fund_id: int, kind: str, cause_type: str,
         cause_id, lines: list[Line], memo: str = "", reverses: JournalEntry | None = None
         ) -> JournalEntry:
    """Post one balanced journal entry, or return the existing entry for this key.

    Posting the same key twice is a no-op that returns the first entry, so a
    retried job or a duplicate bank notification can never double-post.
    """
    existing = JournalEntry.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        return existing
    lines = [l for l in lines if l.amount != 0]
    if len(lines) < 2:
        raise LedgerError("An entry needs at least two non-zero lines.")
    by_currency: dict[str, Decimal] = {}
    for l in lines:
        amount = to_money(l.amount)
        if amount <= 0:
            raise LedgerError(f"Line amounts must be positive, got {amount}.")
        if l.side not in (D, C):
            raise LedgerError(f"Unknown side {l.side!r}.")
        if l.account.fund_id != fund_id:
            raise LedgerError("All lines of an entry must belong to the entry's fund.")
        signed = amount if l.side == D else -amount
        by_currency[l.account.currency] = by_currency.get(l.account.currency, Decimal(0)) + signed
    if any(v != 0 for v in by_currency.values()):
        raise LedgerError(f"Entry does not balance: {by_currency}.")
    try:
        with transaction.atomic():
            entry = JournalEntry.objects.create(
                idempotency_key=idempotency_key, group_id=group_id, fund_id=fund_id,
                kind=kind, cause_type=cause_type, cause_id=str(cause_id), memo=memo[:255],
                reverses=reverses,
            )
            JournalLine.objects.bulk_create(
                JournalLine(entry=entry, account=l.account, side=l.side, amount=to_money(l.amount))
                for l in lines
            )
    except IntegrityError:
        # Lost a race on the same key: the other writer's entry stands.
        return JournalEntry.objects.get(idempotency_key=idempotency_key)
    return entry


def reverse(entry: JournalEntry, *, idempotency_key: str, memo: str = "") -> JournalEntry:
    """Post the mirror image of ``entry``. The original is never touched."""
    lines = [Line(l.account, C if l.side == D else D, l.amount) for l in entry.lines.all()]
    return post(
        idempotency_key=idempotency_key, group_id=entry.group_id, fund_id=entry.fund_id,
        kind="reversal", cause_type="JournalEntry", cause_id=entry.pk, lines=lines,
        memo=memo or f"Reversal of entry {entry.pk}", reverses=entry,
    )


def _signed_sum():
    """Sum of lines signed by each account's normal side (positive = normal)."""
    return Sum(
        Case(
            When(side=F("account__normal_side"), then=F("amount")),
            default=-F("amount"),
            output_field=DecimalField(max_digits=18, decimal_places=2),
        )
    )


def balance(acct: Account) -> Decimal:
    total = JournalLine.objects.filter(account=acct).aggregate(v=_signed_sum())["v"]
    return total or Decimal("0.00")


def balances(fund_id: int, purpose: str) -> dict:
    """Balance per account of one purpose in a fund, keyed by member id for
    member interests and by account id otherwise."""
    rows = (
        JournalLine.objects.filter(account__fund_id=fund_id, account__purpose=purpose)
        .values("account_id", "account__member_id")
        .annotate(v=_signed_sum())
    )
    key = "account__member_id" if purpose == Purpose.MEMBER_INTEREST else "account_id"
    return {r[key]: r["v"] or Decimal("0.00") for r in rows}


def fund_position(fund_id: int) -> dict:
    """Everything a fund holds, by purpose. By double entry, cash always equals
    member interests + unattributed + retained - unexplained outflows."""
    rows = (
        JournalLine.objects.filter(account__fund_id=fund_id)
        .values("account__purpose")
        .annotate(v=_signed_sum())
    )
    out = {p.value: Decimal("0.00") for p in Purpose}
    for r in rows:
        out[r["account__purpose"]] = r["v"] or Decimal("0.00")
    return out


def trial_balance(fund_id: int | None = None) -> Decimal:
    """Total debits minus total credits: zero whenever the ledger is sound."""
    qs = JournalLine.objects.all()
    if fund_id is not None:
        qs = qs.filter(account__fund_id=fund_id)
    agg = qs.aggregate(
        d=Sum(Case(When(side=D, then=F("amount")), default=Value(0),
                   output_field=DecimalField(max_digits=18, decimal_places=2))),
        c=Sum(Case(When(side=C, then=F("amount")), default=Value(0),
                   output_field=DecimalField(max_digits=18, decimal_places=2))),
    )
    return (agg["d"] or Decimal(0)) - (agg["c"] or Decimal(0))
