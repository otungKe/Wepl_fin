"""What happens when the bank feed misbehaves: duplicates, reordering,
missing lines and conflicting resends."""
from dataclasses import replace
from decimal import Decimal

from django.test import TestCase

from connectivity import services as conn
from connectivity.models import Alert, StatementLine
from ledger.models import JournalEntry
from simulator import bank
from simulator.bank import Faults, SimulatorConnector

from .factories import approve_withdrawal, make_group
from .helpers import assert_sound, sync

N = "0012345678901"


class FaultTests(TestCase):
    def setUp(self):
        self.group, self.fund, self.m, self.ea = make_group()
        for member in self.m:
            bank.deposit(N, "1000", msisdn=member.person.msisdn, name="X")
        mandate = approve_withdrawal(self.m, self.fund, "1200")
        bank.withdraw(N, "1200", narration=f"PAY {mandate.reference}")
        bank.credit_interest(N, "20")
        bank.charge(N, "5")

    def test_duplicates_and_reordering_change_nothing(self):
        noisy = SimulatorConnector(Faults(duplicate_rate=1.0, reorder=True, seed=7))
        for _ in range(3):
            result, run = sync(self.ea, noisy)
        self.assertEqual(StatementLine.objects.count(), 8)
        self.assertEqual(JournalEntry.objects.count(), 8)
        self.assertTrue(run.balanced)
        self.assertFalse(Alert.objects.exists())
        assert_sound(self, self.ea)

    def test_missing_lines_are_detected_then_healed_by_the_sweep(self):
        lossy = SimulatorConnector(Faults(withhold_rate=0.5, seed=3))
        _, run = sync(self.ea, lossy)
        self.assertFalse(run.balanced)
        self.assertTrue(run.sequence_gaps or run.difference)
        self.assertTrue(Alert.objects.filter(kind=Alert.Kind.RECONCILIATION_DIFFERENCE).exists())
        _, run = sync(self.ea)  # end-of-day sweep
        self.assertTrue(run.balanced, run.__dict__)
        self.assertEqual(run.difference, 0)
        assert_sound(self, self.ea)

    def test_conflicting_resend_is_flagged_and_not_posted(self):
        sync(self.ea)
        entries = JournalEntry.objects.count()
        original = SimulatorConnector(sweep=True).fetch(N)[0]
        altered = replace(original, amount=original.amount + Decimal("1"))
        result = conn.ingest(self.ea, [altered, altered])
        self.assertEqual(result.conflicts, 2)
        self.assertEqual(Alert.objects.filter(kind=Alert.Kind.STATEMENT_CONFLICT).count(), 1)
        self.assertEqual(JournalEntry.objects.count(), entries)
        assert_sound(self, self.ea)

    def test_reprocessing_a_line_cannot_double_post(self):
        sync(self.ea)
        line = StatementLine.objects.filter(kind="deposit").first()
        before = JournalEntry.objects.count()
        conn._process(self.ea, line)  # e.g. a retried job after a crash
        self.assertEqual(JournalEntry.objects.count(), before)
