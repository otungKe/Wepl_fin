"""Operations on the simulated I&M account, and a connector with fault injection."""
import random
import secrets
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from connectivity.connectors.base import BankLine
from wepl.money import to_money

from .models import SimAccount, SimTransaction


class InsufficientFunds(Exception):
    pass


def open_account(number: str, name: str, opening_balance="0.00") -> SimAccount:
    return SimAccount.objects.create(number=number, name=name, balance=to_money(opening_balance))


@transaction.atomic
def _post(number, kind, amount, *, inflow: bool, **fields) -> SimTransaction:
    acct = SimAccount.objects.select_for_update().get(number=number)
    amount = to_money(amount)
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
    return _post(number, "deposit", amount, inflow=True, counterparty_msisdn=msisdn,
                 counterparty_name=name, reference=reference or number,
                 narration=f"MPESA C2B {msisdn} {name}")


def withdraw(number, amount, *, narration, payee_name="", payee_msisdn=""):
    """Officials pay out from the account (in I&M's app, with dual authorisation)."""
    return _post(number, "withdrawal", amount, inflow=False, narration=narration,
                 counterparty_name=payee_name, counterparty_msisdn=payee_msisdn)


def credit_interest(number, amount):
    return _post(number, "interest", amount, inflow=True, narration="INTEREST CREDIT")


def charge(number, amount, narration="TRANSACTION CHARGE"):
    return _post(number, "charge", amount, inflow=False, narration=narration)


@dataclass
class Faults:
    """What can go wrong between the bank and WEPL."""
    duplicate_rate: float = 0.0   # the same line delivered again
    withhold_rate: float = 0.0    # a line missing from a push feed until the sweep
    reorder: bool = False         # lines arrive out of order
    seed: int = 0


def _to_bank_line(t: SimTransaction) -> BankLine:
    return BankLine(
        bank_txn_id=t.txn_id, sequence=t.sequence, posted_at=t.posted_at, kind=t.kind,
        amount=Decimal(t.amount), narration=t.narration, reference=t.reference,
        counterparty_name=t.counterparty_name, counterparty_msisdn=t.counterparty_msisdn,
        running_balance=Decimal(t.balance_after), raw={"source": "simulator"},
    )


class SimulatorConnector:
    """Push-style feed with injected faults. ``sweep=True`` behaves like the
    bank's end-of-day statement: complete, ordered and without duplicates."""

    def __init__(self, faults: Faults | None = None, sweep: bool = False):
        self.faults = faults or Faults()
        self.sweep = sweep
        self._rng = random.Random(self.faults.seed)

    def fetch(self, account_number: str):
        lines = [_to_bank_line(t) for t in SimTransaction.objects.filter(account__number=account_number)]
        if self.sweep:
            return lines
        f, rng = self.faults, self._rng
        out = [l for l in lines if rng.random() >= f.withhold_rate]
        out += [l for l in out if rng.random() < f.duplicate_rate]
        if f.reorder:
            rng.shuffle(out)
        return out
