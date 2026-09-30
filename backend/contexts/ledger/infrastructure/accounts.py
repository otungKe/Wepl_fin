from django.db import IntegrityError, transaction

from ..domain.accounts import AccountKey
from .models import Account


def _filter(key: AccountKey) -> dict:
    return dict(fund_id=key.fund_id, purpose=key.purpose.value, member_id=key.member_id,
                external_account_id=key.external_account_id, currency=key.currency)


def find(key: AccountKey) -> Account | None:
    return Account.objects.filter(**_filter(key)).first()


def resolve(key: AccountKey) -> Account:
    """Get or create the account for a key; the unique key settles races."""
    found = find(key)
    if found:
        if found.group_id != key.group_id:
            raise IntegrityError("Account key resolves to another group's account.")
        return found
    try:
        with transaction.atomic():
            return Account.objects.create(group_id=key.group_id, normal_side=key.purpose.normal_side.value,
                                          **_filter(key))
    except IntegrityError:
        return Account.objects.get(**_filter(key))
