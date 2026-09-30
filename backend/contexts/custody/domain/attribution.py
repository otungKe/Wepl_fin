"""Deciding which member a pay-in belongs to."""
from __future__ import annotations

import re
from dataclasses import dataclass

from contexts.identity.contract import Msisdn


@dataclass(frozen=True)
class MemberFacts:
    id: int
    code: str
    msisdn: str
    active: bool = True  # False for a membership spell that has ended (ADR-0012)


def attribute(*, reference: str, narration: str, payer_msisdn: str, members: list[MemberFacts],
              remembered_payers: dict[str, int]) -> int | None:
    """In order: a member code quoted in the reference or narration; a payer
    number a corrector has confirmed before; the member's own number.
    Otherwise None: the money is held as unattributed until someone says.

    ``members`` includes spells that ended. A code always means its own spell,
    so a payment quoting an ended spell's code is held for a person to
    decide, never moved to that person's current spell or anyone else."""
    by_code = {m.code.upper(): m for m in members}
    for token in re.findall(r"[A-Za-z0-9]+", f"{reference} {narration}"):
        if token.upper() in by_code:
            quoted = by_code[token.upper()]
            return quoted.id if quoted.active else None
    payer = Msisdn.try_parse(payer_msisdn)
    if payer is None:
        return None
    active = [m for m in members if m.active]
    if remembered_payers.get(payer.value) in {m.id for m in active}:
        return remembered_payers[payer.value]
    return next((m.id for m in active if m.msisdn == payer.value), None)
