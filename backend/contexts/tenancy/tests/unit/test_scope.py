from unittest import TestCase

from contexts.tenancy.domain.scope import entry_refusal


class EntryTests(TestCase):
    def test_a_tenant_or_system_scope_can_be_entered_from_nothing(self):
        self.assertIsNone(entry_refusal(None, False, 7))
        self.assertIsNone(entry_refusal(None, False, None))

    def test_re_entering_the_same_tenant_is_allowed(self):
        self.assertIsNone(entry_refusal(7, False, 7))

    def test_switching_scope_is_refused(self):
        self.assertIn("cannot switch", entry_refusal(7, False, 8))
        self.assertIn("cross-tenant operation while acting", entry_refusal(7, False, None))
        self.assertIn("inside a cross-tenant operation", entry_refusal(None, True, 7))
