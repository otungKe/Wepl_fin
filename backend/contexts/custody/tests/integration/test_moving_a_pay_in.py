"""A pay-in booked in the wrong fund of the account is moved to the fund it
was meant for (ADR-0025): the money keeps its owner, the account's total
does not move, and the pay-in counts in the right fund from then on."""
from django.db import DatabaseError, connection, transaction
from django.test import TestCase

from contexts.audit.infrastructure.models import AuditEvent
from contexts.communities.public import close_fund, open_fund
from contexts.custody.infrastructure.models import LineResolution, StatementLine
from contexts.custody.public import (CustodyError, attribute_payment, line_trail, member_pay_ins, move_pay_in,
                                     reconcile)
from contexts.ledger.public import fund_position, member_balances, trial_balance
from contexts.shared_kernel.money import Money
from simulators.custodian_bank import bank
from tests.scenario import RULES, Scenario

N = "0012345678901"
WHY = "Paid for welfare; left out the fund code"


class MovingAPayInTests(TestCase):
    def setUp(self):
        self.s = Scenario(rules={**RULES, "interest": "retained"})
        self.other = Scenario("Other group", account="0099999999999")
        self.enterContext(self.s.acting())
        self.m, self.main = self.s.m, self.s.fund
        self.welfare = open_fund(self.s.group.id, name="Welfare", code="WEL", actor="test")
        bank.deposit(N, "3000", msisdn="254712000001", name="WANJIKU K")
        bank.deposit(N, "500", msisdn="254712000004", name="KIPRONO C")  # meant for welfare
        self.s.sync()
        self.line = StatementLine.objects.get(amount="500")

    def held(self, fund, member) -> Money:
        return member_balances(fund.id).get(member.id, Money.zero())

    def assert_sound(self):
        self.assertTrue(reconcile(self.s.ea.id).balanced)
        for fund in (self.main, self.welfare):
            self.assertEqual(trial_balance(fund.id), 0)
            self.assertTrue(fund_position(fund.id).invariant_holds)

    def test_a_member_s_pay_in_moves_to_the_fund_it_was_meant_for(self):
        move_pay_in(self.line.pk, self.welfare.id, by=self.m[0].id, reason=WHY)
        kiprono = self.m[3]
        self.assertEqual((self.held(self.main, kiprono), self.held(self.welfare, kiprono)), (Money("0"), Money("500")))
        self.assertEqual((fund_position(self.main.id).cash, fund_position(self.welfare.id).cash),
                         (Money("3000"), Money("500")))
        self.assertEqual([r["outcome"] for r in line_trail(self.line.pk)["resolutions"]],
                         ["attributed", "moved", "attributed"])
        self.assertEqual(member_pay_ins(self.main.id, kiprono.id), [])  # it counts where it is now
        self.assertEqual([a for _, a in member_pay_ins(self.welfare.id, kiprono.id)], [Money("500")])
        event = AuditEvent.objects.get(action="custody.pay_in_moved")
        self.assertEqual((event.data["from_fund_id"], event.data["to_fund_id"], event.data["reason"]),
                         (self.main.id, self.welfare.id, WHY))
        self.assert_sound()

    def test_it_can_move_back(self):
        move_pay_in(self.line.pk, self.welfare.id, by=self.m[0].id, reason=WHY)
        move_pay_in(self.line.pk, self.main.id, by=self.m[1].id, reason="It was for savings after all")
        self.assertEqual(self.held(self.main, self.m[3]), Money("500"))
        self.assertEqual([a for _, a in member_pay_ins(self.main.id, self.m[3].id)], [Money("500")])
        self.assert_sound()

    def test_an_unattributed_pay_in_moves_and_is_then_attributed_there(self):
        bank.deposit(N, "700", msisdn="254733999999", name="UNKNOWN")
        self.s.sync()
        line = StatementLine.objects.get(amount="700")
        move_pay_in(line.pk, self.welfare.id, by=self.m[0].id, reason=WHY)
        self.assertEqual((fund_position(self.main.id).unattributed, fund_position(self.welfare.id).unattributed),
                         (Money("0"), Money("700")))
        attribute_payment(line.pk, self.m[4].id, by=self.m[0].id)
        self.assertEqual(self.held(self.welfare, self.m[4]), Money("700"))
        self.assert_sound()

    def test_nobody_moves_their_own_pay_in_and_only_correctors_move_any(self):
        bank.deposit(N, "200", msisdn="254712000002", name="OTIENO O")
        self.s.sync()
        own = StatementLine.objects.get(amount="200")
        with self.assertRaisesMessage(CustodyError, "Not authorised"):
            move_pay_in(own.pk, self.welfare.id, by=self.m[1].id, reason=WHY)
        with self.assertRaisesMessage(CustodyError, "Not authorised"):
            move_pay_in(self.line.pk, self.welfare.id, by=self.m[4].id, reason=WHY)  # no correct_records

    def test_what_cannot_move(self):
        cases = [
            ("Say why", dict(fund_id=self.welfare.id, reason="  ")),
            ("already in that fund", dict(fund_id=self.main.id, reason=WHY)),
            ("Unknown fund", dict(fund_id=999999, reason=WHY)),
        ]
        for message, kw in cases:
            with self.subTest(message), self.assertRaisesMessage(CustodyError, message):
                move_pay_in(self.line.pk, by=self.m[0].id, **kw)
        old = open_fund(self.s.group.id, name="Old", actor="test")
        close_fund(old.id, actor="test")
        with self.assertRaisesMessage(CustodyError, "cannot move there"):
            move_pay_in(self.line.pk, old.id, by=self.m[0].id, reason=WHY)
        with self.assertRaisesMessage(CustodyError, "cannot move there"):  # invisible to this tenant
            move_pay_in(self.line.pk, self.other.fund.id, by=self.m[0].id, reason=WHY)
        self.assertEqual(LineResolution.objects.filter(line=self.line).count(), 1)

    def test_a_payout_or_interest_line_does_not_move(self):
        bank.credit_interest(N, "10")
        self.s.sync()
        with self.assertRaisesMessage(CustodyError, "Only a pay-in"):
            move_pay_in(StatementLine.objects.get(kind="interest").pk, self.welfare.id, by=self.m[0].id, reason=WHY)

    def test_money_already_spent_or_promised_does_not_move(self):
        ref = self.s.approve("3100")  # main holds 3500, of which 3100 is now promised to a payout
        with self.assertRaisesMessage(CustodyError, "only KES 400.00 not already promised"):
            move_pay_in(self.line.pk, self.welfare.id, by=self.m[0].id, reason=WHY)
        bank.withdraw(N, "3100", narration=f"PAY {ref}", payee_name="Supplier")
        self.s.sync()
        with self.assertRaisesMessage(CustodyError, "hold only"):  # Kiprono's share of it was paid out
            move_pay_in(self.line.pk, self.welfare.id, by=self.m[0].id, reason=WHY)
        self.assert_sound()

    def test_postgresql_refuses_money_taken_out_of_a_fund_and_not_booked_in_another(self):
        last = LineResolution.objects.get(line=self.line)
        with self.assertRaisesMessage(DatabaseError, "not booked in another"), transaction.atomic():
            LineResolution.objects.create(line=self.line, outcome="moved", journal_entry_id=last.journal_entry_id,
                                          membership_id=self.m[3].id)
            with connection.cursor() as c:
                c.execute("SET CONSTRAINTS ALL IMMEDIATE")
