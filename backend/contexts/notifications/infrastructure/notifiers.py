"""Notifier implementations. The SMS provider will be added here once chosen."""
import logging

from django.conf import settings
from django.utils.module_loading import import_string

log = logging.getLogger("wepl.notify")


class LogNotifier:
    def deliver(self, topic: str, payload: dict) -> None:
        log.info("NOTIFY %s %s", topic, payload)


class MemoryNotifier:
    """For tests and demos: keeps delivered messages in memory."""

    def __init__(self):
        self.sent: list = []

    def deliver(self, topic: str, payload: dict) -> None:
        self.sent.append((topic, payload))


def configured_notifier():
    return import_string(settings.WEPL_NOTIFIER)()
