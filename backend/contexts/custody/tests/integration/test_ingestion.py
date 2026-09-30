from django.db import transaction
from django.db.utils import DatabaseError
from django.test import TestCase

from contexts.custody.infrastructure.models import Alert, LineResolution, PayerMapping, StatementLine
from contexts.custody.public import (CustodyError, attribute_payment, explain_outflow, group_summary,
                                     member_statement, record_opening_balances, statement_lines)
from contexts.governance.infrastructure.models import Mandate
from contexts.notifications.infrastructure.models import OutboxEvent
from contexts.shared_kernel.money import Money
from simulators.im_bank import bank
from tests.scenario import RULES, Scenario

N = "0012345678901"


def line_where(**kw):
    return StatementLine.objects.get(**kw)


class ContributionTests(TestCase):
    def setUp(self):
        self.s = Scenario()

    def test_deposit_attributed_by_phone(self):
        bank.deposit(N, "1000", msisdn="254712000004", name="KIPRONO C")
        _, run = self.s.sync()
        self.assertEqual(self.s.balance_of(self.s.m[3]), Money("1000"))
        self.assertTrue(run.balanced)
        self.assertTrue(OutboxEvent.objects.filter(topic="contribution.received").exists())
        self.s.assert_sound(self)

    def test_deposit_attributed_by_member_code(self):
        bank.deposit(N, "500", msisdn="254733999999", name="SPOUSE", reference=f"{N} M05")
        self.s.sync()
        self.assertEqual(self.s.balance_of(self.s.m[4]), Money("500"))

    def test_unknown_payer_held_then_attributed_once_and_remembered(self):
        bank.deposit(N, "700", msisdn="254733999999", name="UNKNOWN")
        self.s.sync()
        self.assertEqual(self.s.assert_sound(self).unattributed, Money("700"))
        line = line_where(amount=700)
        attribute_payment(line.pk, self.s.m[2].id, actor="treasurer")
        self.assertTrue(PayerMapping.objects.filter(msisdn="254733999999").exists())
        bank.deposit(N, "300", msisdn="0733999999", name="UNKNOWN")
        self.s.sync()
        self.assertEqual(self.s.balance_of(self.s.m[2]), Money("1000"))
        self.assertEqual(self.s.assert_sound(self).unattributed, Money("0"))
        with self.assertRaisesMessage(CustodyError, "Only unattributed"):
            attribute_payment(line.pk, self.s.m[1].id, actor="treasurer")

    def test_interest_and_charges_shared_pro_rata(self):
        bank.deposit(N, "3000", msisdn="0712000001", name="A")
        bank.deposit(N, "1000", msisdn="0712000002", name="B")
        bank.credit_interest(N, "40")
        bank.charge(N, "10")
        _, run = self.s.sync()
        self.assertEqual(self.s.balance_of(self.s.m[0]), Money("3022.50"))
        self.assertEqual(self.s.balance_of(self.s.m[1]), Money("1007.50"))
        self.assertTrue(run.balanced)

    def test_retained_interest_and_charges(self):
        s = Scenario("Retained", account="999", rules={**RULES, "interest": "retained", "bank_charges": "retained"})
        bank.deposit("999", "1000", msisdn="0712000001", name="A")
        bank.credit_interest("999", "40")
        bank.charge("999", "15")
        s.sync()
        self.assertEqual(s.assert_sound(self).retained, Money("25"))
        self.assertEqual(s.balance_of(s.m[0]), Money("1000"))


class WithdrawalTests(TestCase):
    def setUp(self):
        self.s = Scenario()
        for i, m in enumerate(self.s.m):
            bank.deposit(N, str(1000 * (i + 1)), msisdn=m.msisdn, name="X")
        self.s.sync()

    def test_withdrawal_quoting_the_mandate_matches(self):
        ref = self.s.approve("1500")
        bank.withdraw(N, "1500", narration=f"PESALINK SUPPLIER {ref}", payee_name="Supplier")
        _, run = self.s.sync()
        self.assertEqual(Mandate.objects.get(reference=ref).status, "executed")
        self.assertFalse(Alert.objects.exists())
        self.assertEqual(self.s.balance_of(self.s.m[4]), Money("4500"))  # 5000 - 1500 * 5/15
        self.assertTrue(run.balanced)
        self.s.assert_sound(self)

    def test_withdrawal_without_reference_matches_a_unique_payee(self):
        ref = self.s.approve("2000", payee_account="0799111222")
        bank.withdraw(N, "2000", narration="MPESA B2C", payee_msisdn="254799111222")
        self.s.sync()
        self.assertEqual(Mandate.objects.get(reference=ref).status, "executed")

    def test_member_payout_is_charged_to_that_member(self):
        ref = self.s.approve("4000", payee_account=self.s.m[3].msisdn, charged=self.s.m[3])
        bank.withdraw(N, "4000", narration=f"EXIT {ref}")
        self.s.sync()
        self.assertEqual(self.s.balance_of(self.s.m[3]), Money("0"))
        self.assertEqual(self.s.balance_of(self.s.m[0]), Money("1000"))

    def test_unapproved_withdrawal_alerts_every_member_then_is_explained(self):
        bank.withdraw(N, "2500", narration="ATM WITHDRAWAL", payee_name="CASH")
        _, run = self.s.sync()
        alert = Alert.objects.get(kind="unmatched_outflow")
        self.assertEqual(OutboxEvent.objects.filter(topic="alert.unmatched_outflow").count(), 5)
        self.assertEqual(self.s.assert_sound(self).unexplained_out, Money("2500"))
        self.assertTrue(run.balanced)  # the books agree with the bank; the alert is the control
        ref = self.s.approve("2500")
        explain_outflow(alert.line_id, Mandate.objects.get(reference=ref).pk, actor="chair")
        alert.refresh_from_db()
        self.assertIsNotNone(alert.resolved_at)
        self.assertEqual(self.s.assert_sound(self).unexplained_out, Money("0"))
        self.s.sync()  # a repeated sync changes nothing
        self.assertEqual(OutboxEvent.objects.filter(topic="alert.unmatched_outflow").count(), 5)

    def test_wrong_amount_or_reused_mandate_is_not_a_match(self):
        ref = self.s.approve("1000")
        bank.withdraw(N, "1200", narration=f"PAY {ref}")
        self.s.sync()
        self.assertEqual(Alert.objects.filter(kind="unmatched_outflow").count(), 1)
        bank.withdraw(N, "1000", narration=f"PAY {ref}")
        bank.withdraw(N, "1000", narration=f"PAY AGAIN {ref}")
        self.s.sync()
        self.assertEqual(Alert.objects.filter(kind="unmatched_outflow").count(), 2)
        self.s.assert_sound(self)

    def test_ambiguous_or_expired_is_alerted(self):
        self.s.approve("1000")
        self.s.approve("1000")
        bank.withdraw(N, "1000", narration="TRANSFER")
        self.s.sync()
        self.assertIn("Several mandates", Alert.objects.get().message)
        ref = self.s.approve("700")
        Mandate.objects.filter(reference=ref).update(status="expired")
        bank.withdraw(N, "700", narration=f"PAY {ref}")
        self.s.sync()
        self.assertIn("expired", Alert.objects.latest("id").message)

    def test_explaining_needs_an_unmatched_line_and_an_exact_unused_mandate(self):
        bank.withdraw(N, "900", narration="ATM")
        self.s.sync()
        line = line_where(amount=900)
        wrong = Mandate.objects.get(reference=self.s.approve("800"))
        with self.assertRaisesMessage(CustodyError, "exactly this amount"):
            explain_outflow(line.pk, wrong.pk, actor="chair")
        deposit_line = line_where(amount=1000)
        with self.assertRaisesMessage(CustodyError, "Only unmatched"):
            explain_outflow(deposit_line.pk, wrong.pk, actor="chair")

    def test_statement_history_is_append_only(self):
        for action in (lambda: StatementLine.objects.update(amount=1), lambda: LineResolution.objects.all().delete()):
            with self.assertRaisesMessage(DatabaseError, "append-only"):
                with transaction.atomic():
                    action()


class OnboardingAndReportTests(TestCase):
    def test_opening_balances_with_remainder_unattributed(self):
        s = Scenario(opening_balance="10000.00")
        record_opening_balances(s.ea.id, statement_balance="10000.00",
                                member_balances={s.m[0].id: "4000", s.m[1].id: "5000"}, actor="treasurer")
        bank.deposit(N, "100", msisdn=s.m[0].msisdn, name="A")
        _, run = s.sync()
        self.assertTrue(run.balanced, run)
        self.assertEqual(s.assert_sound(self).unattributed, Money("1000"))
        stmt = member_statement(s.m[0].id, s.fund.id)
        self.assertEqual((stmt["balance"], len(stmt["lines"])), (Money("4100").amount, 2))
        self.assertEqual(group_summary(s.ea.id)["position"].cash, Money("10100"))
        self.assertEqual([l["outcome"] for l in statement_lines(s.ea.id)], ["opening", "attributed"])

    def test_opening_balances_are_checked(self):
        s = Scenario(opening_balance="100.00")
        with self.assertRaisesMessage(CustodyError, "more than the bank"):
            record_opening_balances(s.ea.id, statement_balance="100", member_balances={s.m[0].id: "200"}, actor="t")
        other = Scenario("Other", account="777")
        with self.assertRaisesMessage(CustodyError, "another group"):
            record_opening_balances(s.ea.id, statement_balance="100", member_balances={other.m[0].id: "50"}, actor="t")
