"""The nightly integrity check: it records, alerts, and never corrects."""
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command
from django.db import DatabaseError, transaction
from django.test import TestCase
from django.utils import timezone

from contexts.audit.infrastructure.models import AuditEvent
from contexts.ledger.contract import FundPosition
from contexts.ledger.infrastructure.models import IntegrityCheck, JournalLine
from contexts.ledger.public import check_books
from contexts.ledger.tests.integration.test_database_rules import Book
from contexts.notifications.public import topics_since
from contexts.shared_kernel.money import Money
from contexts.tenancy.public import tenant

BROKEN = FundPosition(cash=Money("100"), member_interests=Money("90"), unattributed=Money("0"),
                      retained=Money("0"), unexplained_out=Money("0"))


class IntegrityCheckTests(TestCase):
    def setUp(self):
        self.a, self.b = Book("A"), Book("B")
        with tenant(self.b.group.tenant_id):
            self.b.post("b1")
        with tenant(self.a.group.tenant_id):
            self.a.post("a1", "100")
            self.a.post("a2", "40")
        self.since = timezone.now()

    def in_a(self):
        return tenant(self.a.group.tenant_id)

    def test_sound_books_pass_and_are_recorded_without_an_alert(self):
        self.enterContext(self.in_a())
        lines = JournalLine.objects.count()
        checks = check_books()
        self.assertEqual([(c.fund_id, c.currency, c.passed) for c in checks], [(self.a.fund.id, "KES", True)])
        c = checks[0]
        self.assertEqual((c.trial_balance, c.retained, c.unexplained_out), (0, Decimal("140"), Decimal("140")))
        self.assertEqual(c.lines, 4)
        self.assertTrue(c.operation_id.startswith("ledger.integrity_check:"))
        self.assertEqual(JournalLine.objects.count(), lines)  # it reads the books, never writes them
        self.assertNotIn("ops.ledger_integrity_failure", topics_since(self.since))

    def test_each_tenant_checks_and_sees_only_its_own_books(self):
        with self.in_a():
            check_books()
            self.assertEqual(set(IntegrityCheck.objects.values_list("fund_id", flat=True)), {self.a.fund.id})
        with tenant(self.b.group.tenant_id):
            self.assertFalse(IntegrityCheck.objects.exists())
            self.assertEqual([c.fund_id for c in check_books()], [self.b.fund.id])

    def test_a_failure_is_recorded_audited_and_alerted_once(self):
        self.enterContext(self.in_a())
        with mock.patch("contexts.ledger.application.integrity.fund_position", return_value=BROKEN):
            [c] = check_books()
        self.assertFalse(c.passed)
        self.assertFalse(c.invariant_holds)
        self.assertEqual(topics_since(self.since).count("ops.ledger_integrity_failure"), 1)
        self.assertTrue(AuditEvent.objects.filter(action="ledger.integrity_check_failed",
                                                  target_id=str(self.a.fund.id)).exists())
        with mock.patch("contexts.ledger.application.integrity.trial_balance", return_value=Decimal("0.01")):
            [again] = check_books()
        self.assertFalse(again.passed)  # a non-zero trial balance fails on its own
        self.assertEqual(topics_since(self.since).count("ops.ledger_integrity_failure"), 2)  # one per failed check

    def test_results_are_append_only_and_cannot_claim_a_pass_they_did_not_get(self):
        self.enterContext(self.in_a())
        [c] = check_books()
        with self.assertRaisesMessage(DatabaseError, "append-only"), transaction.atomic():
            IntegrityCheck.objects.filter(pk=c.pk).update(passed=False)
        with self.assertRaises(DatabaseError), transaction.atomic():
            IntegrityCheck.objects.create(fund_id=c.fund_id, currency="KES", trial_balance=Decimal("5"), cash=0,
                                          member_interests=0, unattributed=0, retained=0, unexplained_out=0,
                                          invariant_holds=True, passed=True, lines=0)

    def test_the_nightly_command_checks_every_tenant_and_fails_loudly(self):
        call_command("check_ledger_integrity", stdout=mock.MagicMock(), stderr=mock.MagicMock())
        with self.in_a():
            self.assertTrue(IntegrityCheck.objects.filter(fund_id=self.a.fund.id, passed=True).exists())
        with tenant(self.b.group.tenant_id):
            self.assertTrue(IntegrityCheck.objects.filter(fund_id=self.b.fund.id, passed=True).exists())
        with mock.patch("contexts.ledger.application.integrity.fund_position", return_value=BROKEN):
            with self.assertRaisesMessage(CommandError, "failed the integrity check"):
                call_command("check_ledger_integrity", stdout=mock.MagicMock(), stderr=mock.MagicMock())
