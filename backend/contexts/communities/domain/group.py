"""Facts about a group as a whole."""
from enum import StrEnum


class Segment(StrEnum):
    """Which kind of group this is, as the constitution's cover page records
    it. It describes the whole group, not a member's participation: one member
    can save in the main fund and give to a welfare fund in the same group,
    and funds, not the segment, carry what the money is for.

    It exists so the pilot can compare segments (pilot plan V5). The money
    core is group-type-agnostic, so no rule may branch on it (ADR-0012)."""

    SAVINGS = "savings"
    WELFARE = "welfare"
    COLLECTION = "collection"
