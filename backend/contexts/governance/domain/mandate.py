import re
import secrets
from enum import StrEnum

# No 0/O or 1/I, so references survive being read out and retyped.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
MANDATE_REFERENCE = re.compile(r"\bWM[A-HJ-NP-Z2-9]{6}\b")


class Allocation(StrEnum):
    PRO_RATA = "pro_rata"  # shared by all members in proportion to their balances
    MEMBER = "member"      # charged to one member (exit payout, loan)


def new_reference() -> str:
    return "WM" + "".join(secrets.choice(_ALPHABET) for _ in range(6))
