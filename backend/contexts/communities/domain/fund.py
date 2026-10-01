"""A fund is one of a group's named pools of money ("Main savings",
"Welfare"; constitution §3). It holds no balance and no rule: balances are
the ledger's, where the money is held is custody's, and who may spend it is
governance's (ADR-0013; docs/architecture/review-funds-module.md)."""
import re

FUND_NAME_MAX = 80
_CURRENCY = re.compile(r"[A-Z]{3}")


class FundError(ValueError):
    pass


def clean_fund_name(name: str | None) -> str:
    """Trimmed, inner whitespace collapsed; never blank, at most 80 characters."""
    name = " ".join((name or "").split())
    if not name:
        raise FundError("A fund needs a name.")
    if len(name) > FUND_NAME_MAX:
        raise FundError(f"A fund name is at most {FUND_NAME_MAX} characters.")
    return name


def check_currency(currency: str | None) -> str:
    """A well-formed ISO 4217 code, e.g. "KES". Which codes a group may use is
    not decided here (review D3)."""
    if not isinstance(currency, str) or not _CURRENCY.fullmatch(currency):
        raise FundError(f"{currency!r} is not a currency code (three capital letters, e.g. KES).")
    return currency
