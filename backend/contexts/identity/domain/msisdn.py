"""A Kenyan mobile number in international form, e.g. 254712345678."""
from __future__ import annotations

import re
from dataclasses import dataclass


class InvalidMsisdn(ValueError):
    pass


@dataclass(frozen=True)
class Msisdn:
    value: str

    @classmethod
    def parse(cls, raw: str) -> Msisdn:
        digits = re.sub(r"\D", "", raw or "")
        if digits.startswith("0") and len(digits) == 10:
            digits = "254" + digits[1:]
        elif len(digits) == 9 and digits[0] in "71":
            digits = "254" + digits
        if not re.fullmatch(r"254[17]\d{8}", digits):
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
