"""A fund is one of a group's named pools of money ("Main savings",
"Welfare"; constitution §3). It holds no balance and no rule: balances are
the ledger's, where the money is held is custody's, and who may spend it is
governance's (ADR-0013; docs/architecture/review-funds-module.md)."""
import re
from enum import StrEnum

FUND_NAME_MAX = 80
# A fund code is what a member adds to a pay-in reference to say which fund
# the money is for, e.g. "0712597024 WEL" (ADR-0023). Letters only, so it
# can never be read as a mobile number or a member code (M01); at least three
# so it is less often an ordinary word a payer types (Harry, 2026-10-06;
# ADR-0026). A code means one fund of its group for good: it is never given
# to another fund, even after that fund changes code or closes.
_FUND_CODE = re.compile(r"[A-Z]{3,6}")
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


def clean_fund_code(code: str | None) -> str:
    """Three to six letters, kept in capitals; payers may type any case."""
    code = (code or "").strip().upper()
    if not _FUND_CODE.fullmatch(code):
        raise FundError(f"A fund code is three to six letters (e.g. WEL); {code!r} is not.")
    return code
