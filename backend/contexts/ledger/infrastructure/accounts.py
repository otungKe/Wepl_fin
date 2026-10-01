from django.db import IntegrityError, transaction

from ..domain.accounts import AccountKey
from ..domain.journal import LedgerError
from .models import Account

UNIQUE_KEY = "ledger_account_unique_key"


def _filter(key: AccountKey) -> dict:
    """The account's identity within the current tenant. The tenant is not
    named: row-level security scopes every query, and the unique key
    includes it."""
    return dict(fund_id=key.fund_id, purpose=key.purpose.value, member_id=key.member_id,
                external_account_id=key.external_account_id, currency=key.currency)


def find(key: AccountKey) -> Account | None:
    return Account.objects.filter(**_filter(key)).first()


def _in_group(account: Account, key: AccountKey) -> Account:
    if account.group_id != key.group_id:
        raise LedgerError(f"Account key for fund {key.fund_id} resolves to another group's account.")
    return account


def resolve(key: AccountKey) -> Account:
    """Get or create the account for a key; the unique key settles races.
    Both paths apply the same check, and only a lost race on the unique key
    is treated as one: any other refusal propagates as it is."""
    found = find(key)
    if found:
        return _in_group(found, key)
    try:
        with transaction.atomic():
            return Account.objects.create(group_id=key.group_id, normal_side=key.purpose.normal_side.value,
                                          **_filter(key))
    except IntegrityError as exc:
        if getattr(getattr(exc.__cause__, "diag", None), "constraint_name", None) != UNIQUE_KEY:
            raise
        return _in_group(Account.objects.get(**_filter(key)), key)
