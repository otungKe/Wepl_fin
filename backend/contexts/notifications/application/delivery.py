"""Deliver queued messages, at least once each."""
import logging

from django.db import transaction
from django.utils import timezone

from ..infrastructure.models import OutboxEvent
from .ports import Notifier

log = logging.getLogger("wepl.notifications")
MAX_ATTEMPTS = 10


def deliver_pending(notifier: Notifier, *, limit: int) -> int:
    """Each message is claimed under a row lock with SKIP LOCKED, so two workers
    never deliver the same one; a failed delivery is recorded and retried on a
    later pass (each pass tries a message at most once), up to MAX_ATTEMPTS."""
    delivered, tried = 0, []
    for _ in range(limit):
        with transaction.atomic():  # one message: claim, deliver, record
            event = (OutboxEvent.objects.select_for_update(skip_locked=True)
                     .filter(delivered_at__isnull=True, attempts__lt=MAX_ATTEMPTS).exclude(pk__in=tried)
                     .order_by("id").first())
            if event is None:
                break
            tried.append(event.pk)
            event.attempts += 1
            try:
                notifier.deliver(event.topic, event.payload)
            except Exception as exc:  # any provider failure is retried
                event.last_error = repr(exc)[:2000]
                log.warning("outbox %s failed (attempt %s, operation %s): %s",
                            event.pk, event.attempts, event.operation_id, exc)
            else:
                event.delivered_at = timezone.now()
                event.last_error = ""
                delivered += 1
            event.save(update_fields=["attempts", "delivered_at", "last_error"])
    return delivered
