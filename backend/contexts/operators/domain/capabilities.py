"""What each operator role may do (ADR-0021). Fails closed: an action with
no registered rule, or a role not listed, is refused."""
from __future__ import annotations

from enum import StrEnum


class OperatorCapability(StrEnum):
    INBOX = "operations.inbox"          # read every group's open problems
    # found a group; add a member or record that they left; open, rename,
    # code or close a fund; adopt a constitution (ADR-0026)
    GROUPS_SETUP = "groups.setup"
    CUSTODY_LINK = "custody.link"       # link or close a group's bank account
    OPERATORS_MANAGE = "operators.manage"


class Role(StrEnum):
    SUPPORT = "support"
    ONBOARDING = "onboarding"
    ADMIN = "admin"


GRANTS: dict[Role, frozenset[OperatorCapability]] = {
    Role.SUPPORT: frozenset({OperatorCapability.INBOX}),
    Role.ONBOARDING: frozenset({OperatorCapability.INBOX, OperatorCapability.GROUPS_SETUP,
                                OperatorCapability.CUSTODY_LINK}),
    Role.ADMIN: frozenset(OperatorCapability),
}

# Actions that need an authenticator code entered in the last few minutes.
STEP_UP = frozenset({OperatorCapability.INBOX, OperatorCapability.GROUPS_SETUP, OperatorCapability.CUSTODY_LINK,
                     OperatorCapability.OPERATORS_MANAGE})


def allowed(role: str, capability: str) -> bool:
    try:
        return OperatorCapability(capability) in GRANTS.get(Role(role), frozenset())
    except ValueError:
        return False
