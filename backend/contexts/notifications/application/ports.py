from typing import Protocol


class Notifier(Protocol):
    """Delivers one message. Raising means "not delivered; retry later"."""

    def deliver(self, topic: str, payload: dict) -> None: ...
