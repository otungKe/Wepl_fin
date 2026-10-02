"""The bank's statement feed, implementing the custody Connector port."""
import random
from dataclasses import dataclass
from decimal import Decimal

from contexts.custody.contract import BankLine, LineKind

from .models import SimTransaction


@dataclass
class Faults:
    """What can go wrong between the bank and WEPL."""
    duplicate_rate: float = 0.0   # the same line delivered again
    withhold_rate: float = 0.0    # a line missing from a push feed until the sweep
    reorder: bool = False         # lines arrive out of order
    seed: int = 0


def _line(t: SimTransaction) -> BankLine:
    return BankLine(external_id=t.txn_id, sequence=t.sequence, posted_at=t.posted_at, kind=LineKind(t.kind),
                    amount=Decimal(t.amount), narration=t.narration, reference=t.reference,
                    counterparty_name=t.counterparty_name, counterparty_msisdn=t.counterparty_msisdn,
                    running_balance=Decimal(t.balance_after), metadata={"source": "im_simulator"})


class SimulatorConnector:
    """A push feed with injected faults. ``sweep=True`` behaves like the bank's
    end-of-day statement: complete, ordered and without duplicates."""

    def __init__(self, faults: Faults | None = None, sweep: bool = False):
        self.faults = faults or Faults()
        self.sweep = sweep
        self._rng = random.Random(self.faults.seed)

    def fetch(self, account_number: str):
        lines = [_line(t) for t in SimTransaction.objects.filter(account__number=account_number)]
        if self.sweep:
            return lines
        f, rng = self.faults, self._rng
        out = [l for l in lines if rng.random() >= f.withhold_rate]
        out += [l for l in out if rng.random() < f.duplicate_rate]
        if f.reorder:
            rng.shuffle(out)
        return out
