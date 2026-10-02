from django.db import connection
from django.test import TestCase
from django.utils import timezone

from contexts.communities.public import create_group
from contexts.notifications.infrastructure.models import OutboxEvent
from contexts.notifications.infrastructure.notifiers import MemoryNotifier
from contexts.notifications.public import deliver_pending, notify
from contexts.tenancy.public import current_tenant, tenant


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
    """Messages are queued inside a tenant; the worker runs outside any tenant
    and sets each tenant's context itself."""

    def setUp(self):
        self.t = create_group("T", actor="test").tenant_id  # a group is its own tenant

    def queue(self, *args, **kw):
        with tenant(self.t):
            notify(*args, **kw)

    def events(self):
        with tenant(self.t):
            return list(OutboxEvent.objects.all())

    def test_dedupe_key_prevents_double_messages(self):
        self.queue("t", {"a": 1}, dedupe_key="x")
        self.queue("t", {"a": 1}, dedupe_key="x")
        self.assertEqual(len(self.events()), 1)

    def test_the_same_dedupe_key_in_another_tenant_is_a_different_message(self):
        self.queue("t", {"a": 1}, dedupe_key="x")
        other = create_group("U", actor="test").tenant_id
        with tenant(other):
            notify("t", {"a": 2}, dedupe_key="x")
        self.assertEqual(deliver_pending(notifier=MemoryNotifier()), 2)

    def test_provider_failure_is_retried_not_lost(self):
        self.queue("t", {"a": 1})
        flaky = Flaky(failures=1)
        self.assertEqual(deliver_pending(notifier=flaky), 0)
        self.assertIn("timeout", self.events()[0].last_error)
        self.assertEqual(deliver_pending(notifier=flaky), 1)
        self.assertEqual(flaky.sent, [("t", {"a": 1})])
        self.assertEqual(deliver_pending(notifier=flaky), 0)  # delivered once only

    def test_provider_is_called_outside_any_transaction_and_any_tenant(self):
        seen = []

        class Probe(MemoryNotifier):
            def deliver(self, topic, payload):
                seen.append((len(connection.atomic_blocks), current_tenant()))

        self.queue("t", {"a": 1})
        baseline = len(connection.atomic_blocks)  # TestCase's own wrapping
        deliver_pending(notifier=Probe())
        self.assertEqual(seen, [(baseline, None)])

    def test_an_expired_lease_is_reclaimed(self):
        self.queue("t", {"a": 1})
        with tenant(self.t):
            OutboxEvent.objects.update(claimed_until=timezone.now() + timezone.timedelta(minutes=5), attempts=1)
        self.assertEqual(deliver_pending(notifier=MemoryNotifier()), 0)  # another worker holds it
        with tenant(self.t):
            OutboxEvent.objects.update(claimed_until=timezone.now() - timezone.timedelta(seconds=1))
        self.assertEqual(deliver_pending(notifier=MemoryNotifier()), 1)
