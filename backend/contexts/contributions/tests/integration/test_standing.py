"""Arrears from real pay-ins, under the rule the group put in its
constitution (ADR-0022)."""
from datetime import datetime, time, timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from contexts.communities.public import open_fund
from contexts.contributions.public import fund_standing, member_standing
from contexts.governance.public import RulesError, adopt_constitution
from contexts.shared_kernel.money import Money
from simulators.custodian_bank import bank
from simulators.custodian_bank.models import SimTransaction
from tests.scenario import RULES, Scenario

N = "0012345678901"


class StandingTests(TestCase):
    def setUp(self):
        self.s = Scenario()
        self.enterContext(self.s.acting())
        self.base = timezone.localdate()
        self.welfare = open_fund(self.s.group.id, name="Welfare", code="WEL", actor="test")
        self.rule = {"fund_id": self.s.fund.id, "frequency": "weekly", "amount": "1000",
                     "due_day": (self.base + timedelta(days=1)).isoweekday(), "starts_on": self.base.isoformat(),
                     "payment_order": "oldest_first", "joiners_owe_from": "start", "extra_payments": "pay_ahead",
                     "late_fine": {"kind": "fixed", "value": "50", "grace_days": 2}, "leaver_arrears": "written_off"}
        adopt_constitution(self.s.group.id, {**RULES, "contributions": [self.rule]}, actor="test")

    def pay(self, member, amount, day, reference=""):
        txn = bank.deposit(N, amount, msisdn=member.msisdn, name=member.name, reference=reference)
        when = timezone.make_aware(datetime.combine(self.base + timedelta(days=day), time(9)))
        SimTransaction.objects.filter(pk=txn.pk).update(posted_at=when)

    def test_each_member_owes_what_the_rule_says_less_what_they_paid(self):
        m = self.s.m
        self.pay(m[0], "1000", 0)
        self.pay(m[0], "1000", 12)    # the second week's 1000, late
        self.pay(m[1], "4000", 0)     # three weeks and the next one ahead
        self.pay(m[2], "500", 0, reference="WEL")  # welfare: not this fund's
        self.s.sync()
        as_of = self.base + timedelta(days=20)  # due: days 1, 8 and 15
        got = {r.code: r.standing for r in fund_standing(self.s.fund.id, as_of=as_of)}
        self.assertEqual((got["M01"].arrears, got["M01"].fines_total), (Money("1000"), Money("100")))
        self.assertEqual((got["M02"].arrears, got["M02"].paid_ahead), (Money("0"), Money("1000")))
        self.assertEqual((got["M03"].arrears, got["M03"].fines_total), (Money("3000"), Money("150")))
        self.assertIsNone(member_standing(m[0].id, self.welfare.id, as_of=as_of))  # welfare has no rule
        out = StringIO()
        call_command("contribution_standing", "--tenant", self.s.tenant_id, "--fund", self.s.fund.id, stdout=out)
        self.assertIn("arrears", out.getvalue())

    def test_a_rule_is_only_for_an_open_fund_of_the_group(self):
        with self.assertRaisesMessage(RulesError, "not an open fund of this group"):
            adopt_constitution(self.s.group.id, {**RULES, "contributions": [{**self.rule, "fund_id": 999999}]},
                               actor="test")
