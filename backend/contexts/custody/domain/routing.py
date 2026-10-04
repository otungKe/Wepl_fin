"""Which of a group's funds a bank-account movement belongs to (ADR-0023).

A group has one bank account and may have several funds. Harry chose
(2026-10-04): a pay-in goes to the fund whose code the payer added to the
reference ("0712597024 WEL"); without a code, to the group's default fund.
Interest and charges on the account are split among the funds as the
group's constitution says (``account_returns``).
"""
from __future__ import annotations

import re

from contexts.governance.contract import AccountReturns
from contexts.shared_kernel.money import Money

_WORD = re.compile(r"[A-Za-z]+")


def fund_for(reference: str, codes: dict[str, int], default_fund_id: int) -> tuple[int, str]:
    """The fund a pay-in is for, and its reference with the fund code taken
    out, so what is left can name the member. A run of letters that is no
    open fund's code is left in place and the money goes to the default
    fund: the payer named no fund WEPL knows."""
    for word in _WORD.finditer(reference or ""):
        fund_id = codes.get(word.group().upper())
        if fund_id is not None:
            rest = f"{reference[:word.start()]} {reference[word.end():]}"
            return fund_id, " ".join(rest.split())
    return default_fund_id, reference


def unknown_words(reference: str, codes: dict[str, int]) -> list[str]:
    """Runs of two or more letters that are no open fund's code. A member
    code (M01) has a single letter, so it is never one of them."""
    return [w for w in (m.group().upper() for m in _WORD.finditer(reference or "")) if len(w) > 1 and w not in codes]


def split_across_funds(amount: Money, holdings: dict[int, Money], rule: AccountReturns,
                       default_fund_id: int) -> dict[int, Money]:
    """Each fund's part of interest or a charge on the shared account.
    ``holdings`` is what each fund holds at the account just before it. By
    fund balance, funds holding nothing or less take no part; if none holds
    anything, there is no balance to go by and it all goes to the default
    fund."""
    if rule is AccountReturns.BY_FUND_BALANCE:
        weights = {f: h.amount for f, h in holdings.items() if h.is_positive}
        if weights:
            return amount.allocate(weights)
    return {default_fund_id: amount}
