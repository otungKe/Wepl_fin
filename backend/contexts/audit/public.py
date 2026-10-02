"""Record business actions for accountability.

Every entry point (a command, a job, a request) opens an ``operation``; audit
records and queued notifications made inside it carry its id, so one workflow
can be traced from start to finish.
"""
import contextvars
import logging
import uuid
from contextlib import contextmanager

from .infrastructure.models import AuditEvent

log = logging.getLogger("wepl.audit")
_operation: contextvars.ContextVar = contextvars.ContextVar("wepl_operation", default=None)


@contextmanager
def operation(name: str, *, actor: str):
    """Scope one business operation. Nested operations keep the outer id."""
    if _operation.get() is not None:
        yield _operation.get()
        return
    op_id = f"{name}:{uuid.uuid4().hex[:12]}"
    token = _operation.set(op_id)
    log.debug("operation start %s actor=%s", op_id, actor)
    try:
        yield op_id
    finally:
        _operation.reset(token)


def current_operation_id() -> str:
    return _operation.get() or ""


def record(actor: str, action: str, *, target_type: str, target_id, group_id: int | None = None,
           data: dict | None = None) -> None:
    AuditEvent.objects.create(actor=actor, action=action, target_type=target_type, target_id=str(target_id),
                              group_id=group_id, operation_id=current_operation_id(), data=data or {})


def history(*, target_type: str, target_id) -> list[dict]:
    return list(AuditEvent.objects.filter(target_type=target_type, target_id=str(target_id))
                .order_by("id").values("actor", "action", "data", "operation_id", "created_at"))
