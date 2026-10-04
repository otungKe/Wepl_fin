"""The Damm check digit: catches every single mistyped digit and every swap of
two neighbouring digits. Used for group payment codes (ADR-0018), so a
mistyped code is refused before the bank takes the money.

The same table is in SQL (communities 0014); a test keeps the two equal."""

TABLE = (
    "0317598642" "7092154863" "4206871359" "1750983426" "6123045978"
    "3674209581" "5869720134" "8945362017" "9438617205" "2581436790"
)


def _interim(digits: str) -> int:
    i = 0
    for d in digits:
        i = int(TABLE[i * 10 + int(d)])
    return i


def check_digit(digits: str) -> str:
    """The digit to append to ``digits``."""
    return str(_interim(digits))


def is_valid(digits: str) -> bool:
    """True when ``digits`` ends in its own correct check digit."""
    return digits.isdigit() and _interim(digits) == 0
