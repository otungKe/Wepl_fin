"""How a statement line was accounted for, and which corrections are allowed."""
from enum import StrEnum


class Outcome(StrEnum):
    ATTRIBUTED = "attributed"      # a pay-in credited to a member
    UNATTRIBUTED = "unattributed"  # a pay-in held until the payer is known
    INTEREST = "interest"
    CHARGE = "charge"
    MATCHED = "matched"            # a payout under a mandate
    UNMATCHED = "unmatched"        # a payout with no mandate: alert raised
    EXPLAINED = "explained"        # an unmatched payout later tied to a mandate
    OPENING = "opening"


INITIAL = {Outcome.ATTRIBUTED, Outcome.UNATTRIBUTED, Outcome.INTEREST, Outcome.CHARGE, Outcome.MATCHED,
           Outcome.UNMATCHED, Outcome.OPENING}
CORRECTIONS = {Outcome.UNATTRIBUTED: {Outcome.ATTRIBUTED}, Outcome.UNMATCHED: {Outcome.EXPLAINED}}


class InvalidCorrection(ValueError):
    pass


def ensure_correction(current: Outcome | None, new: Outcome) -> None:
    if current is None or new not in CORRECTIONS.get(current, set()):
        raise InvalidCorrection(f"A line that is {current or 'unprocessed'} cannot become {new}.")
