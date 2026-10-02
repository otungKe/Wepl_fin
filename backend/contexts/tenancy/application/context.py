"""Explicit tenant context (foundational decisions 3, 6 and 7).

``tenant(id)`` is the only way to act on tenant-scoped data. It opens a
transaction (or savepoint) and sets a transaction-local database setting that
the row-level security policies read, so the context cannot outlive the
transaction or leak into the next task on a reused connection.

``cross_tenant(reason, actor=...)`` is the only way to act outside a tenant.
It is audited every time."""
import contextvars
from contextlib import contextmanager

from django.db import transaction

from contexts.audit.public import record

from ..domain.scope import TenancyError, entry_refusal
from ..infrastructure import session
from ..infrastructure.models import Tenant

_tenant: contextvars.ContextVar = contextvars.ContextVar("wepl_tenant", default=None)
_system: contextvars.ContextVar = contextvars.ContextVar("wepl_cross_tenant", default=False)


def current_tenant() -> int | None:
    return _tenant.get()


def require_tenant() -> int:
    if _tenant.get() is None:
        raise TenancyError("This operation needs a tenant context.")
    return _tenant.get()


def _check(wanted: int | None) -> None:
    if reason := entry_refusal(_tenant.get(), _system.get(), wanted):
        raise TenancyError(f"Tenant boundary: {reason}.")


@contextmanager
def tenant(tenant_id: int):
    """Act for one tenant. Re-entering the same tenant is a no-op."""
    if tenant_id is None:
        raise TenancyError("A tenant context needs a tenant id.")
    _check(tenant_id)
    if _tenant.get() == tenant_id:
        yield tenant_id
        return
    if not Tenant.objects.filter(pk=tenant_id).exists():
        raise TenancyError(f"Unknown tenant {tenant_id}.")
    token = _tenant.set(tenant_id)
    try:
        with transaction.atomic():
            session.set_tenant(tenant_id)
            yield tenant_id
            session.set_tenant(None)  # on error the rollback clears it instead
    finally:
        _tenant.reset(token)


@contextmanager
def cross_tenant(reason: str, *, actor: str):
    """Declare a system operation outside any tenant boundary. Audited."""
    if not reason:
        raise TenancyError("A cross-tenant operation must say why.")
    _check(None)
    if _system.get():
        yield
        return
    token = _system.set(True)
    try:
        with transaction.atomic():
            session.set_cross_tenant(True)
            record(actor, "tenancy.cross_tenant", target_type="tenancy", target_id="*", data={"reason": reason})
            yield
            session.set_cross_tenant(False)
    finally:
        _system.reset(token)
