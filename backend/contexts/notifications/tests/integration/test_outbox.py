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

    def test_provider_is_called_outside_any_transaction(self):
        from django.db import connection

        seen = []

        class Probe(MemoryNotifier):
            def deliver(self, topic, payload):
                seen.append(len(connection.atomic_blocks))

        notify("t", {"a": 1})
        baseline = len(connection.atomic_blocks)  # TestCase's own wrapping
        deliver_pending(notifier=Probe())
        self.assertEqual(seen, [baseline])

    def test_an_expired_lease_is_reclaimed(self):
        from django.utils import timezone
        notify("t", {"a": 1})
        OutboxEvent.objects.update(claimed_until=timezone.now() + timezone.timedelta(minutes=5), attempts=1)
        self.assertEqual(deliver_pending(notifier=MemoryNotifier()), 0)  # another worker holds it
        OutboxEvent.objects.update(claimed_until=timezone.now() - timezone.timedelta(seconds=1))
        self.assertEqual(deliver_pending(notifier=MemoryNotifier()), 1)
