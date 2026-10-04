"""Operator accounts are provisioned, never self-registered (ADR-0021)."""
import secrets

from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils import timezone

from ..contract import OperatorCapability, OperatorError, OperatorView, Role
from ..domain.capabilities import allowed
from ..infrastructure.models import Operator, OperatorSession
from .log import log
from .sessions import view

BOOTSTRAP = "server:bootstrap"


def _manager(by: OperatorView | None) -> str:
    """Who is provisioning: an operator allowed to manage operators, or, only
    while there is no operator at all, the server's first-admin bootstrap."""
    if by is None:
        if Operator.objects.exists():
            raise OperatorError("Operators already exist: an admin operator must do this.")
        return BOOTSTRAP
    current = Operator.objects.filter(pk=by.id, active=True).first()
    if current is None or not allowed(current.role, OperatorCapability.OPERATORS_MANAGE):
        raise OperatorError("Not authorised to manage operators.")
    return by.actor


@transaction.atomic
def create_operator(email: str, name: str, role: str, *, by: OperatorView | None) -> tuple[OperatorView, str]:
    """The new operator and a one-time password to hand over in person. They
    must change it, and enrol an authenticator, at their first sign-in."""
    actor = _manager(by)
    try:
        role = Role(role)
    except ValueError:
        raise OperatorError(f"role is one of {[r.value for r in Role]}.") from None
    if actor == BOOTSTRAP and role is not Role.ADMIN:
        raise OperatorError("The first operator must be an admin.")
    email = (email or "").strip().lower()
    if "@" not in email or not name:
        raise OperatorError("An operator needs a work email and a name.")
    if Operator.objects.filter(email=email).exists():
        raise OperatorError("An operator with that email already exists.")
    one_time = secrets.token_urlsafe(12)
    o = Operator.objects.create(email=email, name=name, role=role, password=make_password(one_time))
    log("operator.created", operator=o, actor=actor, role=role)
    return view(o), one_time


@transaction.atomic
def deactivate_operator(operator_id: int, *, by: OperatorView) -> OperatorView:
    """Ends every session at once. Deactivated operators are kept: the logs
    name them."""
    actor = _manager(by)
    o = Operator.objects.select_for_update().get(pk=operator_id)
    if o.pk == by.id:
        raise OperatorError("Another admin must deactivate you.")
    o.active = False
    o.save(update_fields=["active"])
    OperatorSession.objects.filter(operator=o, ended_at__isnull=True).update(ended_at=timezone.now())
    log("operator.deactivated", operator=o, actor=actor)
    return view(o)
