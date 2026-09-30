"""Deliver queued messages, at least once each."""
import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ..infrastructure.models import OutboxEvent
from .ports import Notifier

log = logging.getLogger("wepl.notifications")
MAX_ATTEMPTS = 10
LEASE = timedelta(minutes=5)


def deliver_pending(notifier: Notifier, *, limit: int) -> int:
    """Claim a message under a short lease, call the provider with no database
    transaction open, then record the outcome. Two workers never hold the same
    message; a worker that dies mid-call releases it when the lease expires.
    Each pass tries a message at most once, up to MAX_ATTEMPTS in total."""
    delivered, tried = 0, []
    for _ in range(limit):
        event = _claim(exclude=tried)
        if event is None:
            break
        tried.append(event.pk)
        try:
            notifier.deliver(event.topic, event.payload)  # never inside a transaction
        except Exception as exc:  # any provider failure is retried on a later pass
            _record(event.pk, error=repr(exc)[:2000])
            log.warning("outbox %s failed (attempt %s, operation %s): %s",
                        event.pk, event.attempts, event.operation_id, exc)
        else:
            _record(event.pk, error=None)
            delivered += 1
    return delivered


def _claim(*, exclude) -> OutboxEvent | None:
    now = timezone.now()
    with transaction.atomic():  # claim: lock, lease, count the attempt
        event = (OutboxEvent.objects.select_for_update(skip_locked=True)
                 .filter(Q(claimed_until__isnull=True) | Q(claimed_until__lt=now),
                         delivered_at__isnull=True, attempts__lt=MAX_ATTEMPTS)
                 .exclude(pk__in=exclude).order_by("id").first())
        if event is None:
            return None
        event.attempts += 1
        event.claimed_until = now + LEASE
        event.save(update_fields=["attempts", "claimed_until"])
        return event


def _record(event_id: int, *, error: str | None) -> None:
    fields = {"claimed_until": None}
    if error is None:
        fields.update(delivered_at=timezone.now(), last_error="")
    else:
        fields.update(last_error=error)
    OutboxEvent.objects.filter(pk=event_id).update(**fields)
