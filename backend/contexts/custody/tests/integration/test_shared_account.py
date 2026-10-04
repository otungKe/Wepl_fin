"""One bank account holds all of a group's funds (ADR-0023; Harry,
2026-10-04): a pay-in goes to the fund whose code it quotes, else to the
default fund; a payout spends the fund its mandate names; interest and
charges split as the group's constitution says; the account reconciles
against all its funds together."""
from django.test import TestCase

from contexts.audit.infrastructure.models import AuditEvent
from contexts.communities.public import CommunityError, close_fund, open_fund, set_fund_code
from contexts.custody.infrastructure.models import Alert, LineResolution, StatementLine
from contexts.custody.public import attribute_payment, explain_outflow, group_summary, reconcile
from contexts.governance.infrastructure.models import Mandate
from contexts.ledger.public import fund_position, member_balances, trial_balance
from contexts.shared_kernel.money import Money
from simulators.custodian_bank import bank
from tests.scenario import RULES, Scenario

N = "0012345678901"


class SharedAccountTests(TestCase):
    def setUp(self, rules=None):
        self.s = Scenario(rules=rules or {**RULES, "account_returns": "by_fund_balance"})
        self.enterContext(self.s.acting())
        self.main = self.s.fund
        self.welfare = open_fund(self.s.group.id, name="Welfare", code="wel", actor="test")

    def held(self, fund, member) -> Money:
        return member_balances(fund.id).get(member.id, Money.zero())

    def cash(self, fund) -> Money:
        return fund_position(fund.id).cash

    def assert_balanced(self):
        self.assertTrue(reconcile(self.s.ea.id).balanced)
        for fund in (self.main, self.welfare):
            self.assertEqual(trial_balance(fund.id), 0)
            self.assertTrue(fund_position(fund.id).invariant_holds)

    def fill(self, main="3000", welfare="1000"):
        bank.deposit(N, main, msisdn="254712000001", name="WANJIKU K")
        bank.deposit(N, welfare, msisdn="254712000002", name="OTIENO O", reference="WEL")
        self.s.sync()

    def test_a_fund_code_sends_a_pay_in_to_that_fund(self):
        bank.deposit(N, "1000", msisdn="254712000004", name="KIPRONO C")
        bank.deposit(N, "300", msisdn="254733999999", name="SPOUSE", reference="0712000004 wel")
        bank.deposit(N, "200", msisdn="254712000005", name="MUTUA M", reference="WEL")
        self.s.sync()
        self.assertEqual(self.welfare.code, "WEL")
        self.assertEqual(self.held(self.main, self.s.m[3]), Money("1000"))
        self.assertEqual(self.held(self.welfare, self.s.m[3]), Money("300"))
        self.assertEqual(self.held(self.welfare, self.s.m[4]), Money("200"))
        self.assertEqual((self.cash(self.main), self.cash(self.welfare)), (Money("1000"), Money("500")))
        self.assert_balanced()
        summary = group_summary(self.s.ea.id)
        self.assertEqual(summary["position"].cash, Money("1500"))
        self.assertEqual({f["fund"]: f["default"] for f in summary["funds"]}, {"Main savings": True, "Welfare": False})
        self.assertEqual({r["code"]: r["balance"] for r in summary["members"]}["M04"], Money("1300").amount)

    def test_a_code_no_open_fund_has_goes_to_the_default_fund(self):
        bank.deposit(N, "400", msisdn="254712000004", name="KIPRONO C", reference="WLF")
        self.s.sync()
        self.assertEqual(self.held(self.main, self.s.m[3]), Money("400"))
        self.assertEqual(self.cash(self.welfare), Money("0"))

    def test_interest_and_charges_split_by_what_each_fund_holds(self):
        self.fill()
        bank.credit_interest(N, "40")
        bank.charge(N, "8")
        self.s.sync()
        self.assertEqual(self.held(self.main, self.s.m[0]), Money("3024"))
        self.assertEqual(self.held(self.welfare, self.s.m[1]), Money("1008"))
        interest = StatementLine.objects.get(kind="interest")
        self.assertEqual(LineResolution.objects.filter(line=interest).count(), 2)  # one entry per fund
        self.assert_balanced()

    def test_a_payout_spends_the_fund_its_mandate_names(self):
        self.fill()
        ref = self.s.approve("600", fund=self.welfare)
        bank.withdraw(N, "600", narration=f"PAY {ref}", payee_name="Supplier")
        self.s.sync()
        self.assertEqual(Mandate.objects.get(reference=ref).status, "executed")
        self.assertEqual(self.held(self.welfare, self.s.m[1]), Money("400"))
        self.assertEqual(self.held(self.main, self.s.m[0]), Money("3000"))
        self.assert_balanced()

    def test_an_outflow_explained_by_another_funds_mandate_moves_there(self):
        self.fill()
        bank.withdraw(N, "500", narration="ATM WITHDRAWAL", payee_name="CASH")
        self.s.sync()
        alert = Alert.objects.get(kind="unmatched_outflow")
        self.assertEqual(fund_position(self.main.id).unexplained_out, Money("500"))  # held in the default fund
        ref = self.s.approve("500", fund=self.welfare)
        explain_outflow(alert.line_id, Mandate.objects.get(reference=ref).pk, by=self.s.m[0].id)
        self.assertEqual(fund_position(self.main.id).unexplained_out, Money("0"))
        self.assertEqual((self.cash(self.main), self.cash(self.welfare)), (Money("3000"), Money("500")))
        self.assertEqual(self.held(self.welfare, self.s.m[1]), Money("500"))
        self.assert_balanced()

    def test_an_unknown_payer_for_a_fund_is_attributed_in_that_fund(self):
        bank.deposit(N, "700", msisdn="254733999999", name="UNKNOWN", reference="WEL")
        self.s.sync()
        self.assertEqual(fund_position(self.welfare.id).unattributed, Money("700"))
        line = StatementLine.objects.get(kind="deposit")
        attribute_payment(line.pk, self.s.m[2].id, by=self.s.m[1].id)
        self.assertEqual(self.held(self.welfare, self.s.m[2]), Money("700"))
        self.assertEqual(self.held(self.main, self.s.m[2]), Money("0"))
        self.assert_balanced()


class DefaultFundReturnsTests(SharedAccountTests):
    """The other choice: everything on the account goes to the default fund."""

    def setUp(self):
        super().setUp(rules=RULES)

    def test_interest_and_charges_split_by_what_each_fund_holds(self):
        self.fill()
        bank.credit_interest(N, "40")
        bank.charge(N, "8")
        self.s.sync()
        self.assertEqual(self.held(self.main, self.s.m[0]), Money("3032"))
        self.assertEqual(self.held(self.welfare, self.s.m[1]), Money("1000"))
        self.assert_balanced()


class FundCodeTests(TestCase):
    def setUp(self):
        self.s = Scenario()
        self.enterContext(self.s.acting())

    def test_a_code_is_letters_and_means_one_open_fund(self):
        for bad in ("W", "W1", "WELFARE", "WE L", ""):
            with self.subTest(bad), self.assertRaisesMessage(CommunityError, "two to six letters"):
                open_fund(self.s.group.id, name=f"Fund {bad}", code=bad, actor="test")
        old = open_fund(self.s.group.id, name="Old welfare", code="wel", actor="test")
        with self.assertRaisesMessage(CommunityError, "already has the code WEL"):
            open_fund(self.s.group.id, name="Welfare", code="WEL", actor="test")
        close_fund(old.id, actor="test")  # a closed fund's code is free again
        welfare = open_fund(self.s.group.id, name="Welfare", code="WEL", actor="test")
        self.assertEqual(set_fund_code(welfare.id, "wf", actor="t").code, "WF")
        self.assertTrue(AuditEvent.objects.filter(action="fund.code_set", data__to="WF").exists())
        with self.assertRaisesMessage(CommunityError, "already has the code WF"):
            set_fund_code(self.s.fund.id, "WF", actor="t")
