"""One bank account holds all of a group's funds (ADR-0023; Harry,
2026-10-04): a pay-in goes to the fund whose code it quotes, else to the
default fund; a payout spends the fund its mandate names; interest and
charges split as the group's constitution says; the account reconciles
against all its funds together."""
from django.test import TestCase

from contexts.audit.infrastructure.models import AuditEvent
from contexts.communities.public import CommunityError, close_fund, open_fund, set_fund_code
from contexts.custody.infrastructure.models import Alert, LineResolution, StatementLine
from contexts.custody.public import (CustodyError, attribute_payment, explain_outflow, group_summary, keep_pay_in,
                                     move_pay_in, reconcile)
from contexts.governance.infrastructure.models import Mandate
from contexts.ledger.public import entry_fund, fund_position, member_balances, trial_balance
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


class UnclearCodeTests(TestCase):
    """A reference that names no one fund goes to the default fund, and a
    corrector is asked to settle it (Harry, 2026-10-06; ADR-0026)."""

    def setUp(self):
        self.s = Scenario()
        self.enterContext(self.s.acting())
        self.main = self.s.fund
        self.welfare = open_fund(self.s.group.id, name="Welfare", code="WEL", actor="test")
        self.edu = open_fund(self.s.group.id, name="Education", code="EDU", actor="test")

    def pay(self, reference):
        bank.deposit(N, "400", msisdn="254712000004", name="KIPRONO C", reference=reference)
        self.s.sync()
        return StatementLine.objects.order_by("-id").first()

    def alert(self, line):
        return Alert.objects.filter(kind=Alert.Kind.FUND_CODE_UNCLEAR, line=line).first()

    def test_an_unknown_or_ambiguous_code_goes_to_the_default_fund_with_an_alert(self):
        for reference, why in (("0712000004 WLF", "WLF is not the code"), ("WEL EDU", "two funds (WEL and EDU)")):
            with self.subTest(reference):
                line = self.pay(reference)
                self.assertEqual(entry_fund(LineResolution.objects.get(line=line).journal_entry_id), self.main.id)
                self.assertIn(why, self.alert(line).message)
                self.assertIn("Main savings", self.alert(line).message)
        self.assertEqual(fund_position(self.welfare.id).cash, Money("0"))

    def test_one_fund_named_is_clear_and_the_code_is_kept_on_the_line(self):
        for reference in ("0712000004 WEL", "WEL WEL", "0712000004", "M04"):
            with self.subTest(reference):
                line = self.pay(reference)
                self.assertIsNone(self.alert(line))
        notes = list(LineResolution.objects.order_by("id").values_list("note", flat=True))
        self.assertEqual(notes[:2], ["Fund code WEL", "Fund code WEL"])

    def test_a_corrector_moves_it_or_keeps_it_and_either_settles_the_alert(self):
        moved, kept = self.pay("0712000004 WLF"), self.pay("M04 WELFARE")
        move_pay_in(moved.pk, self.welfare.id, by=self.s.m[0].id, reason="WLF was a typo for WEL")
        self.assertIsNotNone(self.alert(moved).resolved_at)
        with self.assertRaisesMessage(CustodyError, "Say why"):
            keep_pay_in(kept.pk, by=self.s.m[0].id, reason=" ")
        keep_pay_in(kept.pk, by=self.s.m[0].id, reason="Main savings, as the member confirmed")
        self.assertIn("Kept in Main savings", self.alert(kept).resolution_note)
        self.assertTrue(AuditEvent.objects.filter(action="custody.pay_in_kept").exists())
        with self.assertRaisesMessage(CustodyError, "no open question"):
            keep_pay_in(kept.pk, by=self.s.m[0].id, reason="again")
        self.assertEqual((fund_position(self.main.id).cash, fund_position(self.welfare.id).cash),
                         (Money("400"), Money("400")))

    def test_only_a_corrector_keeps_a_pay_in(self):
        line = self.pay("WLF")
        with self.assertRaisesMessage(CustodyError, "Not authorised"):
            keep_pay_in(line.pk, by=self.s.m[3].id, reason="mine")
        self.assertIsNone(self.alert(line).resolved_at)


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

    def test_a_code_is_letters_and_means_one_fund_for_good(self):
        """Three to six letters; once a fund has used a code, no other fund of
        the group ever gets it, so a payer quoting it is never misdirected
        (Harry, 2026-10-06; ADR-0026)."""
        for bad in ("W", "WE", "W1", "WELFARE", "WE L", ""):
            with self.subTest(bad), self.assertRaisesMessage(CommunityError, "three to six letters"):
                open_fund(self.s.group.id, name=f"Fund {bad}", code=bad, actor="test")
        old = open_fund(self.s.group.id, name="Old welfare", code="wel", actor="test")
        with self.assertRaisesMessage(CommunityError, "already has the code WEL"):
            open_fund(self.s.group.id, name="Welfare", code="WEL", actor="test")
        close_fund(old.id, actor="test")
        with self.assertRaisesMessage(CommunityError, "never given to a different fund"):
            open_fund(self.s.group.id, name="Welfare", code="WEL", actor="test")  # closed, still its code
        welfare = open_fund(self.s.group.id, name="Welfare", code="WLF", actor="test")
        self.assertEqual(set_fund_code(welfare.id, "wfd", actor="t").code, "WFD")
        self.assertTrue(AuditEvent.objects.filter(action="fund.code_set", data__to="WFD").exists())
        with self.assertRaisesMessage(CommunityError, "already has the code WFD"):
            set_fund_code(self.s.fund.id, "WFD", actor="t")
        with self.assertRaisesMessage(CommunityError, "never given to a different fund"):
            set_fund_code(self.s.fund.id, "WLF", actor="t")  # Welfare's earlier code stays Welfare's
        self.assertEqual(set_fund_code(welfare.id, "WLF", actor="t").code, "WLF")  # its own again
