from decimal import Decimal

from django.db import transaction
from django.db.utils import DatabaseError
from django.test import TestCase

from connectivity import reports
from connectivity import services as conn
from connectivity.models import Alert, LineResolution, PayerMapping, StatementLine
from governance.models import Mandate
from platform_core.models import OutboxEvent
from simulator import bank

from .factories import DEFAULT_RULES, approve_withdrawal, make_group
from .helpers import P, assert_sound, member_balance, sync

N = "0012345678901"


class ContributionTests(TestCase):
    def setUp(self):
        self.group, self.fund, self.m, self.ea = make_group()

    def test_deposit_attributed_by_phone(self):
        bank.deposit(N, "1000", msisdn="254712000004", name="KIPRONO C")
        _, run = sync(self.ea)
        self.assertEqual(member_balance(self.ea, self.m[3]), Decimal("1000.00"))
        self.assertTrue(run.balanced)
        self.assertTrue(OutboxEvent.objects.filter(topic="contribution.received").exists())
        assert_sound(self, self.ea)

    def test_deposit_attributed_by_member_code_in_reference(self):
        bank.deposit(N, "500", msisdn="254733999999", name="SPOUSE", reference=f"{N} M05")
        sync(self.ea)
        self.assertEqual(member_balance(self.ea, self.m[4]), Decimal("500.00"))

    def test_unknown_payer_held_then_attributed_and_remembered(self):
        bank.deposit(N, "700", msisdn="254733999999", name="UNKNOWN")
        sync(self.ea)
        pos = assert_sound(self, self.ea)
        self.assertEqual(pos[P.UNATTRIBUTED_IN], Decimal("700.00"))
        line = StatementLine.objects.get(amount=700)
        conn.attribute_payment(line, self.m[2], actor="treasurer")
        self.assertEqual(member_balance(self.ea, self.m[2]), Decimal("700.00"))
        self.assertTrue(PayerMapping.objects.filter(msisdn="254733999999").exists())
        bank.deposit(N, "300", msisdn="0733999999", name="UNKNOWN")
        sync(self.ea)
        self.assertEqual(member_balance(self.ea, self.m[2]), Decimal("1000.00"))
        pos = assert_sound(self, self.ea)
        self.assertEqual(pos[P.UNATTRIBUTED_IN], 0)
        with self.assertRaises(conn.ConnectivityError):
            conn.attribute_payment(line, self.m[1], actor="treasurer")

    def test_interest_and_charges_shared_pro_rata(self):
        bank.deposit(N, "3000", msisdn="0712000001", name="A")
        bank.deposit(N, "1000", msisdn="0712000002", name="B")
        bank.credit_interest(N, "40")
        bank.charge(N, "10")
        _, run = sync(self.ea)
        self.assertEqual(member_balance(self.ea, self.m[0]), Decimal("3022.50"))
        self.assertEqual(member_balance(self.ea, self.m[1]), Decimal("1007.50"))
        self.assertTrue(run.balanced)

    def test_retained_interest_and_charges(self):
        group, fund, m, ea = make_group("Retained", account_number="999",
                                        rules={**DEFAULT_RULES, "interest": "retained", "bank_charges": "retained"})
        bank.deposit("999", "1000", msisdn="0712000001", name="A")
        bank.credit_interest("999", "40")
        bank.charge("999", "15")
        sync(ea)
        pos = assert_sound(self, ea)
        self.assertEqual(pos[P.RETAINED], Decimal("25.00"))
        self.assertEqual(member_balance(ea, m[0]), Decimal("1000.00"))


class WithdrawalTests(TestCase):
    def setUp(self):
        self.group, self.fund, self.m, self.ea = make_group()
        for i, member in enumerate(self.m):
            bank.deposit(N, str(1000 * (i + 1)), msisdn=member.person.msisdn, name="X")
        sync(self.ea)

    def test_withdrawal_with_reference_matches_mandate(self):
        mandate = approve_withdrawal(self.m, self.fund, "1500")
        bank.withdraw(N, "1500", narration=f"PESALINK SUPPLIER {mandate.reference}", payee_name="Supplier")
        _, run = sync(self.ea)
        mandate.refresh_from_db()
        self.assertEqual(mandate.status, Mandate.Status.EXECUTED)
        self.assertFalse(Alert.objects.filter(kind=Alert.Kind.UNMATCHED_OUTFLOW).exists())
        self.assertEqual(member_balance(self.ea, self.m[4]), Decimal("4500.00"))  # 5000 - 1500 * 5/15
        self.assertTrue(run.balanced)
        assert_sound(self, self.ea)

    def test_withdrawal_without_reference_matches_unique_payee(self):
        mandate = approve_withdrawal(self.m, self.fund, "2000", payee_account="0799111222")
        bank.withdraw(N, "2000", narration="MPESA B2C", payee_msisdn="254799111222")
        sync(self.ea)
        mandate.refresh_from_db()
        self.assertEqual(mandate.status, Mandate.Status.EXECUTED)

    def test_member_payout_charged_to_that_member(self):
        mandate = approve_withdrawal(self.m, self.fund, "4000", payee_account=self.m[3].person.msisdn,
                                     charged_member=self.m[3])
        bank.withdraw(N, "4000", narration=f"EXIT {mandate.reference}")
        sync(self.ea)
        self.assertEqual(member_balance(self.ea, self.m[3]), Decimal("0.00"))
        self.assertEqual(member_balance(self.ea, self.m[0]), Decimal("1000.00"))

    def test_unapproved_withdrawal_raises_alert_to_every_member(self):
        bank.withdraw(N, "2500", narration="ATM WITHDRAWAL", payee_name="CASH")
        _, run = sync(self.ea)
        alert = Alert.objects.get(kind=Alert.Kind.UNMATCHED_OUTFLOW)
        self.assertIn("2500", alert.message)
        self.assertEqual(OutboxEvent.objects.filter(topic="alert.unmatched_outflow").count(), 5)
        pos = assert_sound(self, self.ea)
        self.assertEqual(pos[P.UNEXPLAINED_OUT], Decimal("2500.00"))
        self.assertTrue(run.balanced)  # the books still agree with the bank; the alert is the control

        mandate = approve_withdrawal(self.m, self.fund, "2500")
        conn.explain_outflow(alert.line, mandate, actor="chair")
        alert.refresh_from_db()
        self.assertIsNotNone(alert.resolved_at)
        pos = assert_sound(self, self.ea)
        self.assertEqual(pos[P.UNEXPLAINED_OUT], 0)

    def test_wrong_amount_or_reused_mandate_is_not_a_match(self):
        mandate = approve_withdrawal(self.m, self.fund, "1000")
        bank.withdraw(N, "1200", narration=f"PAY {mandate.reference}")
        sync(self.ea)
        self.assertEqual(Alert.objects.filter(kind=Alert.Kind.UNMATCHED_OUTFLOW).count(), 1)
        bank.withdraw(N, "1000", narration=f"PAY {mandate.reference}")
        bank.withdraw(N, "1000", narration=f"PAY AGAIN {mandate.reference}")
        sync(self.ea)
        self.assertEqual(Alert.objects.filter(kind=Alert.Kind.UNMATCHED_OUTFLOW).count(), 2)
        assert_sound(self, self.ea)

    def test_ambiguous_match_without_reference_is_alerted(self):
        approve_withdrawal(self.m, self.fund, "1000")
        approve_withdrawal(self.m, self.fund, "1000")
        bank.withdraw(N, "1000", narration="TRANSFER")
        sync(self.ea)
        self.assertIn("Several mandates", Alert.objects.get().message)

    def test_expired_mandate_does_not_authorise(self):
        mandate = approve_withdrawal(self.m, self.fund, "1000")
        Mandate.objects.filter(pk=mandate.pk).update(status=Mandate.Status.EXPIRED)
        bank.withdraw(N, "1000", narration=f"PAY {mandate.reference}")
        sync(self.ea)
        self.assertIn("expired", Alert.objects.get().message)

    def test_statement_history_is_append_only(self):
        line = StatementLine.objects.first()
        with self.assertRaisesMessage(DatabaseError, "append-only"):
            with transaction.atomic():
                StatementLine.objects.filter(pk=line.pk).update(amount=1)
        with self.assertRaisesMessage(DatabaseError, "append-only"):
            with transaction.atomic():
                LineResolution.objects.all().delete()


class OnboardingAndReportTests(TestCase):
    def test_opening_balances_with_remainder_unattributed(self):
        group, fund, m, ea = make_group(opening_balance="10000.00")
        conn.record_opening_balances(ea, statement_balance="10000.00",
                                     member_balances={m[0]: "4000", m[1]: "5000"}, actor="treasurer")
        bank.deposit(N, "100", msisdn=m[0].person.msisdn, name="A")
        _, run = sync(ea)
        self.assertTrue(run.balanced, run.__dict__)
        pos = assert_sound(self, ea)
        self.assertEqual(pos[P.UNATTRIBUTED_IN], Decimal("1000.00"))
        stmt = reports.member_statement(m[0], fund.pk)
        self.assertEqual(stmt["balance"], Decimal("4100.00"))
        self.assertEqual(len(stmt["lines"]), 2)
        summary = reports.group_summary(ea)
        self.assertEqual(summary["cash"], Decimal("10100.00"))

    def test_opening_balances_cannot_exceed_bank(self):
        group, fund, m, ea = make_group(opening_balance="100.00")
        with self.assertRaises(conn.ConnectivityError):
            conn.record_opening_balances(ea, statement_balance="100", member_balances={m[0]: "200"}, actor="t")
