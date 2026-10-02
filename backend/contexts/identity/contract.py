"""Types other contexts may use, including in their pure domain code."""
from dataclasses import dataclass

from .domain.msisdn import InvalidMsisdn, Msisdn

__all__ = ["InvalidMsisdn", "Msisdn", "PersonView"]


@dataclass(frozen=True)
class PersonView:
    id: int
    msisdn: str
    name: str
