from __future__ import annotations

from dataclasses import dataclass

from contexts.shared_kernel.money import Money


@dataclass(frozen=True)
class FundPosition:
    """Everything a fund holds, by purpose.

    Because every entry balances, cash always equals member interests plus
    unattributed receipts plus retained money, minus unexplained outflows.
    """

    cash: Money
    member_interests: Money
    unattributed: Money
    retained: Money
    unexplained_out: Money

    @property
    def invariant_holds(self) -> bool:
        return self.cash == self.member_interests + self.unattributed + self.retained - self.unexplained_out
