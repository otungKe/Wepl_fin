from .models import AuditEvent


def record(actor: str, action: str, target, data: dict | None = None) -> AuditEvent:
    return AuditEvent.objects.create(
        actor=str(actor)[:120],
        action=action,
        target_type=type(target).__name__,
        target_id=str(target.pk),
        data=data or {},
    )
