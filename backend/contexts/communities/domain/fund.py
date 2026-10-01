"""A fund is one of a group's named pools of money ("Main savings",
"Welfare"; constitution §3). It holds no balance and no rule: balances are
the ledger's, where the money is held is custody's, and who may spend it is
governance's (ADR-0013; docs/architecture/review-funds-module.md)."""
import re
from enum import StrEnum

FUND_NAME_MAX = 80
_CURRENCY = re.compile(r"[A-Z]{3}")
# Harry, 2026-10-01: the pilot holds Kenyan shillings only. Money, the ledger's
# queries and custody's statements all assume KES today; allowing another
# currency is an ADR, then a migration (communities 0011 checks it too).
CURRENCIES = ("KES",)


class FundStatus(StrEnum):
    """OPEN, then CLOSED, and never back (Harry, 2026-10-01). A group that
    needs the pool again opens a new fund, so old records keep meaning the old
    one. A fund is never deleted."""

    OPEN = "open"
    CLOSED = "closed"


class FundError(ValueError):
    pass


def ensure_open(status: str) -> None:
    if FundStatus(status) is not FundStatus.OPEN:
        raise FundError("This fund is closed; open a new fund instead.")


def clean_fund_name(name: str | None) -> str:
    """Trimmed, inner whitespace collapsed; never blank, at most 80 characters.
    Case is kept as given, but names are unique per group regardless of case
    (Harry, 2026-10-01): "Savings" and "savings" are the same fund to members."""
    name = " ".join((name or "").split())
    if not name:
        raise FundError("A fund needs a name.")
    if len(name) > FUND_NAME_MAX:
        raise FundError(f"A fund name is at most {FUND_NAME_MAX} characters.")
    return name


def check_currency(currency: str | None) -> str:
    """One of the currencies a fund may be opened in: only KES for the pilot."""
    if not isinstance(currency, str) or not _CURRENCY.fullmatch(currency):
        raise FundError(f"{currency!r} is not a currency code (three capital letters, e.g. KES).")
    if currency not in CURRENCIES:
        raise FundError(f"Funds are held in {', '.join(CURRENCIES)} only; {currency} is not supported.")
    return currency
