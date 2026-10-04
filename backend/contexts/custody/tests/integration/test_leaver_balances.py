"""What a leaver's balance shares in (ADR-0014): the group's choice, as it
stood on the day the member left. Five members each hold 1000; Kiprono
(M04) leaves; then the bank pays 100 interest and takes a 10 charge."""
from django.test import TestCase

from contexts.communities.public import leave_group
from contexts.governance.public import adopt_constitution
from contexts.shared_kernel.money import Money
from simulators.custodian_bank import bank
from tests.scenario import RULES, Scenario

N = "0012345678901"
UNTIL_PAID = {**RULES, "leaver_balances": "shares_until_paid"}
FROZEN = {**RULES, "leaver_balances": "frozen_at_leaving"}


class LeaverBalanceTests(TestCase):
    def start(self, rules):
        self.s = Scenario(rules=rules)
        self.enterContext(self.s.acting())
        for m in self.s.m:
            bank.deposit(N, "1000", msisdn=m.msisdn, name="X")
        self.s.sync()
        self.leaver = self.s.m[3]
        self.stayers = [m for m in self.s.m if m is not self.leaver]
        leave_group(self.leaver.id, actor="test")

    def returns(self):
        bank.credit_interest(N, "100")
        bank.charge(N, "10")
        self.s.sync()

    def assert_balances(self, leaver, stayer):
        self.assertEqual(self.s.balance_of(self.leaver), Money(leaver))
        self.assertEqual({self.s.balance_of(m) for m in self.stayers}, {Money(stayer)})
        self.s.assert_sound(self)

    def test_frozen_at_leaving_the_balance_earns_and_pays_nothing(self):
        self.start(FROZEN)
        self.returns()
        self.assert_balances("1000", "1022.50")

    def test_shares_until_paid_the_balance_keeps_sharing_interest_and_charges(self):
        self.start(UNTIL_PAID)
        self.returns()
        self.assert_balances("1018", "1018")

    def test_a_leaver_never_shares_a_payout_made_after_they_left(self):
        self.start(UNTIL_PAID)
        bank.withdraw(N, "400", narration=self.s.approve("400"))
        self.s.sync()
        self.assert_balances("1000", "900")

    def test_once_paid_out_a_leaver_stops_sharing(self):
        self.start(UNTIL_PAID)
        bank.withdraw(N, "1000", narration=self.s.approve("1000", charged=self.leaver))
        self.s.sync()
        self.returns()
        self.assert_balances("0", "1022.50")

    def test_the_rule_in_force_on_the_day_they_left_applies(self):
        self.start(UNTIL_PAID)
        adopt_constitution(self.s.group.id, FROZEN, actor="test")  # changed after Kiprono left
        self.returns()
        self.assert_balances("1018", "1018")

    def test_a_later_change_does_not_reach_back_to_an_earlier_leaver(self):
        self.start(FROZEN)
        adopt_constitution(self.s.group.id, UNTIL_PAID, actor="test")
        self.returns()
        self.assert_balances("1000", "1022.50")
