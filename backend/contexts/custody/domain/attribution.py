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


def attribute(*, reference: str, narration: str, payer_msisdn: str, members: list[MemberFacts],
              remembered_payers: dict[str, int]) -> int | None:
    """In order: a member code quoted in the reference or narration; a payer
    number the treasurer has confirmed before; the member's own number.
    Otherwise None: the money is held as unattributed until someone says."""
    by_code = {m.code.upper(): m.id for m in members}
    for token in re.findall(r"[A-Za-z0-9]+", f"{reference} {narration}"):
        if token.upper() in by_code:
            return by_code[token.upper()]
    payer = Msisdn.try_parse(payer_msisdn)
    if payer is None:
        return None
    active_ids = {m.id for m in members}
    if remembered_payers.get(payer.value) in active_ids:
        return remembered_payers[payer.value]
    return next((m.id for m in members if m.msisdn == payer.value), None)
