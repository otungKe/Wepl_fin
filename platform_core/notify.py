"""Notification port. SMS is on hold while a provider is chosen; until then
messages go to the log, and the outbox keeps a permanent copy of each one."""
import logging

log = logging.getLogger("wepl.notify")


class LogNotifier:
    def deliver(self, topic: str, payload: dict) -> None:
        log.info("NOTIFY %s %s", topic, payload)


class MemoryNotifier:
    """For tests and demos: keeps delivered messages in memory."""

    sent: list = []

    def deliver(self, topic: str, payload: dict) -> None:
        MemoryNotifier.sent.append((topic, payload))
