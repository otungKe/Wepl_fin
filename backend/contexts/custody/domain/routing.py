"""Which of a group's funds a bank-account movement belongs to (ADR-0023).

A group has one bank account and may have several funds. Harry chose
(2026-10-04): a pay-in goes to the fund whose code the payer added to the
reference ("0712597024 WEL"); without a code, to the group's default fund:
the fund its bank account was linked with. A code that is unknown, or two
codes naming different funds, also go there, with an alert (ADR-0026).
Interest and charges on the account are split among the funds as the
group's constitution says (``account_returns``).
"""
from __future__ import annotations

import re

from contexts.governance.contract import AccountReturns
from contexts.shared_kernel.money import Money

_WORD = re.compile(r"[A-Za-z]+")


def quoted_codes(reference: str, codes: dict[str, int]) -> list[str]:
    """The fund codes the reference quotes, each once, in order."""
    found = []
    for word in _WORD.finditer(reference or ""):
        if (code := word.group().upper()) in codes and code not in found:
            found.append(code)
    return found


def fund_for(reference: str, codes: dict[str, int], default_fund_id: int) -> tuple[int, str]:
    """The fund a pay-in is for, and its reference with the fund code taken
    out, so what is left can name the member. A reference that quotes no open
    fund's code, or the codes of two funds, goes to the default fund
    unchanged: the payer named no one fund WEPL knows (``unclear_code`` says
    why, for an alert; Harry, 2026-10-06, ADR-0026)."""
    quoted = quoted_codes(reference, codes)
    if len({codes[c] for c in quoted}) != 1:
        return default_fund_id, reference
    word = next(w for w in _WORD.finditer(reference) if w.group().upper() == quoted[0])
    return codes[quoted[0]], " ".join(f"{reference[:word.start()]} {reference[word.end():]}".split())


def unknown_words(reference: str, codes: dict[str, int]) -> list[str]:
    """Runs of two or more letters that are no open fund's code. A member
    code (M01) has a single letter, so it is never one of them."""
    return [w for w in (m.group().upper() for m in _WORD.finditer(reference or "")) if len(w) > 1 and w not in codes]


def unclear_code(reference: str, codes: dict[str, int]) -> str:
    """Why a pay-in went to the default fund although its reference seems to
    name a fund, or "" if it does not: it quotes the codes of two different
    funds, or letters that are no open fund's code (a typo, a closed fund's
    old code). A reference naming exactly one fund is clear, whatever else
    it says; the collections check refuses stray letters before payment."""
    quoted = quoted_codes(reference, codes)
    if len({codes[c] for c in quoted}) > 1:
        return f"it quotes the codes of two funds ({' and '.join(quoted)})"
    if not quoted and (unknown := unknown_words(reference, codes)):
        return f"{unknown[0]} is not the code of one of the group's open funds"
    return ""


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
