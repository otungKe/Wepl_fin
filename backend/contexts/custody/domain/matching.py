"""Deciding whether a payout was authorised by a mandate."""
from __future__ import annotations

from dataclasses import dataclass

from contexts.governance.contract import MANDATE_REFERENCE, MandateStatus, MandateView
from contexts.identity.contract import Msisdn
from contexts.shared_kernel.money import Money


@dataclass(frozen=True)
class Match:
    mandate_id: int | None
    reason: str


def quoted_references(narration: str, reference: str) -> list[str]:
    return MANDATE_REFERENCE.findall(f"{narration} {reference}")


def match_outflow(*, amount: Money, payee_msisdn: str, quoted: list[str], referenced: MandateView | None,
                  candidates: list[MandateView]) -> Match:
    """A quoted mandate reference must name an issued mandate for exactly this
    amount. With no reference, only a single issued mandate with this amount
    (and this payee, when the bank reports one) is accepted; anything
    ambiguous is not a match, because a wrong match would hide an alert."""
    if quoted:
        if referenced is None:
            return Match(None, f"Reference {quoted[0]} is not a mandate of this fund.")
        if referenced.status is not MandateStatus.ISSUED:
            return Match(None, f"Mandate {referenced.reference} is {referenced.status}.")
        if referenced.amount != amount:
            return Match(None, f"Mandate {referenced.reference} is for {referenced.amount}, the bank paid {amount}.")
        return Match(referenced.id, f"Matched by reference {referenced.reference}.")
    payee = Msisdn.try_parse(payee_msisdn)
    if payee is not None:
        candidates = [m for m in candidates if Msisdn.try_parse(m.payee_account) == payee]
    if len(candidates) == 1:
        return Match(candidates[0].id, "Matched by amount and payee (no reference quoted).")
    if candidates:
        return Match(None, "Several mandates could match; the treasurer must quote the reference.")
    return Match(None, "No approved mandate for this payment.")
