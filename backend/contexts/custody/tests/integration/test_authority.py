"""Only an active official of the account's group may correct its books
(guideline: test the unauthorized actor). Every refusal leaves no trace in
the ledger."""
from django.test import TestCase

from contexts.audit.public import history
from contexts.communities.infrastructure.models import Membership
from contexts.custody.infrastructure.models import LineResolution, StatementLine
from contexts.custody.public import CustodyError, attribute_payment, explain_outflow, record_opening_balances
from contexts.governance.infrastructure.models import Mandate
from contexts.ledger.public import trial_balance
from simulators.im_bank import bank
from tests.scenario import Scenario

N = "0012345678901"


class CorrectionAuthorityTests(TestCase):
    def setUp(self):
        self.s = Scenario()
        self.neighbour = Scenario("Neighbour", account="778", tenant_id=self.s.tenant_id)  # same tenant
        self.foreign = Scenario("Foreign", account="777")  # another tenant
        self.enterContext(self.s.acting())
        bank.deposit(N, "5000", msisdn=self.s.m[0].msisdn, name="CHAIR")
        bank.deposit(N, "700", msisdn="254733999999", name="UNKNOWN")
        self.s.sync()
        self.line = StatementLine.objects.get(amount=700)

    def refused(self, fn, message):
        before = LineResolution.objects.count()
        with self.assertRaisesMessage(CustodyError, message):
            fn()
        self.assertEqual(LineResolution.objects.count(), before)
        self.s.assert_sound(self)

    def test_an_ordinary_member_cannot_attribute(self):
        self.refused(lambda: attribute_payment(self.line.pk, self.s.m[4].id, by=self.s.m[3].id), "not an official")

    def test_an_official_cannot_credit_themselves(self):
        treasurer = self.s.m[1]
        self.refused(lambda: attribute_payment(self.line.pk, treasurer.id, by=treasurer.id), "own favour")
        attribute_payment(self.line.pk, treasurer.id, by=self.s.m[0].id)  # another official may
        self.assertEqual(self.s.balance_of(treasurer).amount, 700)

    def test_an_official_who_left_cannot_attribute(self):
        Membership.objects.filter(pk=self.s.m[0].id).update(status="left")
        self.refused(lambda: attribute_payment(self.line.pk, self.s.m[4].id, by=self.s.m[0].id), "not an active")

    def test_another_groups_official_cannot_correct(self):
        self.refused(lambda: attribute_payment(self.line.pk, self.s.m[4].id, by=self.neighbour.m[1].id),
                     "not a member of this group")

    def test_another_tenants_official_is_not_even_visible(self):
        self.refused(lambda: attribute_payment(self.line.pk, self.s.m[4].id, by=self.foreign.m[1].id),
                     "unknown official")

    def test_an_unknown_actor_is_refused(self):
        self.refused(lambda: attribute_payment(self.line.pk, self.s.m[4].id, by=999999), "unknown official")

    def test_explaining_an_outflow_needs_an_official(self):
        bank.withdraw(N, "900", narration="ATM")
        self.s.sync()
        line = StatementLine.objects.get(amount=900)
        mandate = Mandate.objects.get(reference=self.s.approve("900"))
        self.refused(lambda: explain_outflow(line.pk, mandate.pk, by=self.s.m[3].id), "not an official")
        self.assertEqual(Mandate.objects.get(pk=mandate.pk).status, "issued")
        explain_outflow(line.pk, mandate.pk, by=self.s.m[2].id)

    def test_the_audit_trail_names_the_official(self):
        attribute_payment(self.line.pk, self.s.m[4].id, by=self.s.m[2].id)
        event = [e for e in history(target_type="statement_line", target_id=self.line.pk)
                 if e["action"] == "custody.payment_attributed"][0]
        self.assertEqual(event["actor"], self.s.m[2].msisdn)


class OpeningBalanceAuthorityTests(TestCase):
    def test_opening_balances_need_two_different_officials(self):
        s = Scenario(opening_balance="1000.00")
        self.enterContext(s.acting())
        balances = {s.m[3].id: "1000"}
        for by, confirmed_by, message in [(s.m[1], s.m[1], "same official"), (s.m[1], s.m[3], "not an official"),
                                         (s.m[3], s.m[1], "not an official")]:
            with self.subTest(message), self.assertRaisesMessage(CustodyError, message):
                record_opening_balances(s.ea.id, statement_balance="1000", member_balances=balances, by=by.id,
                                        confirmed_by=confirmed_by.id)
        self.assertFalse(StatementLine.objects.exists())
        self.assertEqual(trial_balance(s.fund.id), 0)
        record_opening_balances(s.ea.id, statement_balance="1000", member_balances=balances, by=s.m[1].id,
                                confirmed_by=s.m[0].id)
        self.assertEqual(s.balance_of(s.m[3]).amount, 1000)
