"""Rules for the data a person carries: their name. Their number is ``Msisdn``."""

NAME_MAX = 120  # the column's length


class IdentityError(ValueError):
    pass


def clean_name(name: str | None) -> str:
    """The name groups and messages will show for a person. Inner whitespace
    collapses to single spaces. Empty and over-long names are refused rather
    than stored blank or cut short: a person's name is seen by every group
    they join, so the caller must learn it was not accepted."""
    name = " ".join((name or "").split())
    if not name:
        raise IdentityError("A person needs a name.")
    if len(name) > NAME_MAX:
        raise IdentityError(f"A name is at most {NAME_MAX} characters.")
    return name
