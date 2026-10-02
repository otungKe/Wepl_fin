from .application.delivery import deliver_pending as _deliver
from .application.ports import Notifier
from .infrastructure.models import OutboxEvent
from .infrastructure.notifiers import configured_notifier

from contexts.audit.public import current_operation_id

__all__ = ["Notifier", "notify", "deliver_pending", "pending_count"]


def notify(topic: str, payload: dict, *, dedupe_key: str | None = None) -> None:
    """Queue a message. Call inside the transaction that made the change, so
    the message exists if and only if the change committed. A repeated
    ``dedupe_key`` is ignored, so retried workflows never message twice."""
    if dedupe_key and OutboxEvent.objects.filter(dedupe_key=dedupe_key).exists():
        return
    OutboxEvent.objects.create(topic=topic, payload=payload, dedupe_key=dedupe_key,
                               operation_id=current_operation_id())


def deliver_pending(limit: int = 100, notifier: Notifier | None = None) -> int:
    return _deliver(notifier or configured_notifier(), limit=limit)


def pending_count() -> int:
    return OutboxEvent.objects.filter(delivered_at__isnull=True).count()


def topics_since(when) -> list[str]:
    return list(OutboxEvent.objects.filter(created_at__gte=when).values_list("topic", flat=True))
