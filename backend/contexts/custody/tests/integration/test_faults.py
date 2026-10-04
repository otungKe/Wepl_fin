"""When the custodian's feed misbehaves: duplicates, reordering, missing lines,
conflicting resends, and a crash between storing a line and accounting for it."""
from dataclasses import replace
from decimal import Decimal

from django.test import TestCase

from contexts.custody.application.ingestion import account_for
from contexts.custody.infrastructure.models import Alert, ExternalAccount, StatementLine
from contexts.custody.public import ingest, reconcile
from contexts.ledger.infrastructure.models import JournalEntry
from simulators.custodian_bank import bank
from simulators.custodian_bank.connector import Faults, SimulatorConnector
from tests.scenario import Scenario

N = "0012345678901"


class FaultTests(TestCase):
    def setUp(self):
        self.s = Scenario()
        self.enterContext(self.s.acting())
        for m in self.s.m:
            bank.deposit(N, "1000", msisdn=m.msisdn, name="X")
        ref = self.s.approve("1200")
        bank.withdraw(N, "1200", narration=f"PAY {ref}")
        bank.credit_interest(N, "20")
        bank.charge(N, "5")

    def test_duplicates_and_reordering_change_nothing(self):
        noisy = SimulatorConnector(Faults(duplicate_rate=1.0, reorder=True, seed=7))
        for _ in range(3):
            _, run = self.s.sync(noisy)
        self.assertEqual(StatementLine.objects.count(), 8)
        self.assertEqual(JournalEntry.objects.count(), 8)
        self.assertTrue(run.balanced)
        self.assertFalse(Alert.objects.exists())
        self.s.assert_sound(self)

    def test_missing_lines_are_detected_then_healed_by_the_sweep(self):
        _, run = self.s.sync(SimulatorConnector(Faults(withhold_rate=0.5, seed=3)))
        self.assertFalse(run.balanced)
        self.assertTrue(run.sequence_gaps or run.difference)
        self.assertTrue(Alert.objects.filter(kind="recon_difference").exists())
        _, run = self.s.sync()
        self.assertTrue(run.balanced, run)
        self.assertEqual(run.difference, 0)
        self.s.assert_sound(self)

    def test_conflicting_resend_is_flagged_and_not_posted(self):
        self.s.sync()
        entries = JournalEntry.objects.count()
        original = SimulatorConnector(sweep=True).fetch(N)[0]
        altered = replace(original, amount=original.amount + Decimal("1"))
        result = ingest(self.s.ea.id, [altered, altered])
        self.assertEqual(result.conflicts, 2)
        self.assertEqual(Alert.objects.filter(kind="statement_conflict").count(), 1)
        self.assertEqual(JournalEntry.objects.count(), entries)
        self.s.assert_sound(self)

    def test_reprocessing_a_line_cannot_double_post(self):
        self.s.sync()
        before = JournalEntry.objects.count()
        ea = ExternalAccount.objects.get(pk=self.s.ea.id)
        for line in StatementLine.objects.all():
            account_for(ea, line)  # e.g. a retried job after a crash
        self.assertEqual(JournalEntry.objects.count(), before)

    def test_lines_left_out_without_a_numbering_gap_break_the_running_balance(self):
        """A statement whose numbering is derived from the statement itself
        shows no gap when lines are left out. Here a deposit and a charge
        that cancel out are missing, with a line between them, so the closing
        balance agrees too: only the running balance shows it."""
        bank.deposit(N, "300", msisdn=self.s.m[0].msisdn, name="X")
        bank.deposit(N, "50", msisdn=self.s.m[1].msisdn, name="X")
        bank.charge(N, "300")
        bank.deposit(N, "20", msisdn=self.s.m[2].msisdn, name="X")
        lines = SimulatorConnector(sweep=True).fetch(N)
        kept = [l for l in lines if l.amount != Decimal("300")]
        renumbered = [replace(l, sequence=n) for n, l in enumerate(kept, start=1)]
        ingest(self.s.ea.id, renumbered)
        run = reconcile(self.s.ea.id)
        self.assertEqual((run.sequence_gaps, run.difference), ([], 0))
        n = len(renumbered)
        self.assertEqual(run.balance_breaks, [n - 1, n])  # the lines after each missing 300
        self.assertFalse(run.balanced)
        self.assertIn("running balance broken at", Alert.objects.get(kind="recon_difference").message)
