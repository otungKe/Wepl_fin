"""Notifier implementations. The SMS provider will be added here once chosen."""
import logging

from django.conf import settings
from django.utils.module_loading import import_string

from ..domain.redaction import for_log

log = logging.getLogger("wepl.notify")


class LogNotifier:
    """Stand-in while SMS is on hold. Logs are not a private channel, so
    phone numbers and names are masked; the outbox row keeps the full message."""

    def deliver(self, topic: str, payload: dict) -> None:
        log.info("NOTIFY %s %s", topic, for_log(payload))


class MemoryNotifier:
    """For tests and demos: keeps delivered messages in memory."""

    def __init__(self):
        self.sent: list = []

    def deliver(self, topic: str, payload: dict) -> None:
        self.sent.append((topic, payload))


def configured_notifier():
    return import_string(settings.WEPL_NOTIFIER)()
