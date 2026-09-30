from django.test import TestCase

from contexts.notifications.infrastructure.models import OutboxEvent
from contexts.notifications.infrastructure.notifiers import MemoryNotifier
from contexts.notifications.public import deliver_pending, notify


class Flaky(MemoryNotifier):
    def __init__(self, failures):
        super().__init__()
        self.failures = failures

    def deliver(self, topic, payload):
        if self.failures:
            self.failures -= 1
            raise TimeoutError("provider timeout")
        super().deliver(topic, payload)


class OutboxTests(TestCase):
    def test_dedupe_key_prevents_double_messages(self):
        notify("t", {"a": 1}, dedupe_key="x")
        notify("t", {"a": 1}, dedupe_key="x")
        self.assertEqual(OutboxEvent.objects.count(), 1)

    def test_provider_failure_is_retried_not_lost(self):
        notify("t", {"a": 1})
        flaky = Flaky(failures=1)
        self.assertEqual(deliver_pending(notifier=flaky), 0)
        event = OutboxEvent.objects.get()
        self.assertIn("timeout", event.last_error)
        self.assertEqual(deliver_pending(notifier=flaky), 1)
        self.assertEqual(flaky.sent, [("t", {"a": 1})])
        self.assertEqual(deliver_pending(notifier=flaky), 0)  # delivered once only
