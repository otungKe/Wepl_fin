"""What other contexts and the API see of operators."""
from dataclasses import dataclass

from .domain.capabilities import OperatorCapability, Role
from .domain.signin import Stage

__all__ = ["COOKIE", "NotSignedIn", "OperatorCapability", "OperatorError", "OperatorView", "Role", "Stage"]

# The operator session cookie. Its own name, so a member session (when member
# login exists) is never mistaken for an operator's (ADR-0021).
COOKIE = "wepl_operator"


class OperatorError(ValueError):
    """A request the operator can fix: a weak password, a wrong code."""


class NotSignedIn(PermissionError):
    """No session, an expired or unfinished one, or one not allowed this action."""


@dataclass(frozen=True)
class OperatorView:
    id: int
    email: str
    name: str
    role: Role
    active: bool

    @property
    def actor(self) -> str:
        """How the audit trail names this operator."""
        return f"operator:{self.id}"
