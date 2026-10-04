"""Break-glass commands run on the server name a real operator too
(ADR-0021): their email and a current authenticator code."""
from django.db import transaction

from ..contract import NotSignedIn, OperatorView
from ..domain.capabilities import allowed
from ..infrastructure.models import Operator
from .log import log
from .sessions import _code_ok, _locked, view


def operator_at_console(email: str, code: str, capability: str) -> OperatorView:
    with transaction.atomic():  # a wrong code is counted even though the command then fails
        o = Operator.objects.select_for_update().filter(email=(email or "").strip().lower()).first()
        ok = (o is not None and o.active and not _locked(o) and o.enrolled_at is not None
              and _code_ok(o, code) and allowed(o.role, capability))
        if ok:
            log("operator.console", operator=o, actor=f"operator:{o.pk}", capability=str(capability))
    if not ok:
        raise NotSignedIn("Unknown operator, wrong or used code, or not allowed.")
    return view(o)
