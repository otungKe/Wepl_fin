"""A Kenyan mobile number in international form, e.g. 254712345678.

The policy is deliberate:

- **Shape and prefix, not allocation.** A number is a Kenyan mobile number if
  it is 07xxxxxxxx or 01xxxxxxxx in local form. WEPL does not check which
  ranges an operator has actually assigned: allocations change, and keeping a
  copy here would go stale. So 0199999999 is accepted.
- **One stored form.** Local (0712 345 678), bare (712345678) and
  international (+254 712 345 678, 00254712345678, +254 (0)712 345 678)
  inputs all become 254712345678. Spaces, ``+``, ``-``, ``.`` and brackets
  are formatting and are ignored.
- **A number, not text containing one.** Anything else in the input (letters,
  ``/``, ``#``...) is refused, so "call 0712345678" is not read as a number.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_FORMATTING = re.compile(r"[\s+\-.()]")


class InvalidMsisdn(ValueError):
    pass


@dataclass(frozen=True)
class Msisdn:
    value: str

    @classmethod
    def parse(cls, raw: str) -> Msisdn:
        digits = _FORMATTING.sub("", raw or "")
        if digits.startswith("00254"):  # the international dialling prefix
            digits = digits[2:]
        if digits.startswith("2540") and len(digits) == 13:  # +254 (0)712...: the trunk 0 kept by mistake
            digits = "254" + digits[4:]
        elif digits.startswith("0") and len(digits) == 10:
            digits = "254" + digits[1:]
        elif len(digits) == 9 and digits[0] in "71":
            digits = "254" + digits
        if not re.fullmatch(r"254[17][0-9]{8}", digits):
            raise InvalidMsisdn(f"{raw!r} is not a Kenyan mobile number.")
        return cls(digits)

    @classmethod
    def try_parse(cls, raw: str) -> Msisdn | None:
        try:
            return cls.parse(raw)
        except InvalidMsisdn:
            return None

    def __str__(self) -> str:
        return self.value
