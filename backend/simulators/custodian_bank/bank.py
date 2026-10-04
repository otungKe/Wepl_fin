"""What happens at the bank: pay-ins, payouts, interest and charges."""
import secrets

from django.db import transaction
from django.utils import timezone

from contexts.shared_kernel.money import Money

from .models import SimAccount, SimTransaction


class InsufficientFunds(Exception):
    pass


def open_account(number: str, name: str, opening_balance="0.00") -> SimAccount:
    return SimAccount.objects.create(number=number, name=name, balance=Money.of(opening_balance).amount)


def balance(number: str) -> Money:
    return Money(SimAccount.objects.get(number=number).balance)


@transaction.atomic
def _post(number, kind, amount, *, inflow: bool, **fields) -> SimTransaction:
    acct = SimAccount.objects.select_for_update().get(number=number)
    amount = Money.of(amount).amount
    if amount <= 0:
        raise ValueError("Amount must be positive.")
    if not inflow and acct.balance < amount:
        raise InsufficientFunds(f"{number} has {acct.balance}, cannot pay {amount}.")
    acct.balance += amount if inflow else -amount
    txn = SimTransaction.objects.create(
        account=acct, txn_id="IM" + secrets.token_hex(6).upper(), sequence=acct.next_sequence,
        posted_at=timezone.now(), kind=kind, amount=amount, balance_after=acct.balance, **fields)
    acct.next_sequence += 1
    acct.save(update_fields=["balance", "next_sequence"])
    return txn


def deposit(number, amount, *, msisdn, name, reference=""):
    """A member pays paybill 542542 with the chama account number as reference."""
    return _post(number, "deposit", amount, inflow=True, counterparty_msisdn=msisdn, counterparty_name=name,
                 reference=reference or number, narration=f"MPESA C2B {msisdn} {name}")


def withdraw(number, amount, *, narration, payee_name="", payee_msisdn=""):
    """Officials pay out in the bank's own channels, under its dual authorisation."""
    return _post(number, "withdrawal", amount, inflow=False, narration=narration, counterparty_name=payee_name,
                 counterparty_msisdn=payee_msisdn)


def credit_interest(number, amount):
    return _post(number, "interest", amount, inflow=True, narration="INTEREST CREDIT")


def charge(number, amount, narration="TRANSACTION CHARGE"):
    return _post(number, "charge", amount, inflow=False, narration=narration)
