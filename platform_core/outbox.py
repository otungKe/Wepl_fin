import logging

from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from .models import OutboxEvent

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 10


def emit(topic: str, payload: dict) -> OutboxEvent:
    return OutboxEvent.objects.create(topic=topic, payload=payload)


def deliver_pending(limit: int = 100) -> int:
    """Deliver undelivered events oldest first. Each event is claimed with a row
    lock and SKIP LOCKED, so two workers never deliver the same event."""
    from django.conf import settings

    notifier = import_string(settings.WEPL_NOTIFIER)()
    delivered = 0
    for _ in range(limit):
        with transaction.atomic():
            event = (
                OutboxEvent.objects.select_for_update(skip_locked=True)
                .filter(delivered_at__isnull=True, attempts__lt=MAX_ATTEMPTS)
                .order_by("id")
                .first()
            )
            if event is None:
                break
            event.attempts += 1
            try:
                notifier.deliver(event.topic, event.payload)
            except Exception as exc:  # delivery failures are retried, never lost
                event.last_error = repr(exc)[:2000]
                log.warning("Outbox event %s failed: %s", event.pk, exc)
            else:
                event.delivered_at = timezone.now()
                event.last_error = ""
                delivered += 1
            event.save(update_fields=["attempts", "delivered_at", "last_error"])
    return delivered
