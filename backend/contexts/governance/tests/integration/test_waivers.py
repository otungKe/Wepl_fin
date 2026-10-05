"""Waivers of a member's arrears or fines (ADR-0022): decided like a
withdrawal, never by the member they are for, and moving no money."""
from datetime import timedelta

from django.db import DatabaseError, transaction
from django.test import TestCase
from django.utils import timezone

from contexts.communities.public import open_fund
from contexts.contributions.public import member_standing
from contexts.governance.infrastructure.models import Waiver
from contexts.governance.public import (GovernanceError, adopt_constitution, cancel_waiver, decide_waiver,
                                        eligible_waiver_approvers, propose_waiver)
from contexts.ledger.public import fund_position
from contexts.shared_kernel.money import Money
from tests.scenario import RULES, Scenario


class WaiverTests(TestCase):
    def setUp(self):
        self.s = Scenario()
        self.enterContext(self.s.acting())
        self.fines = open_fund(self.s.group.id, name="Fines", code="FIN", actor="test")
        today = timezone.localdate()
        rule = {"fund_id": self.s.fund.id, "frequency": "weekly", "amount": "1000",
                "due_day": (today + timedelta(days=1)).isoweekday(), "starts_on": today.isoformat(),
                "payment_order": "oldest_first", "joiners_owe_from": "start", "extra_payments": "pay_ahead",
                "late_fine": {"kind": "fixed", "value": "50", "grace_days": 2, "pay_into": self.fines.id},
                "leaver_arrears": "written_off"}
        adopt_constitution(self.s.group.id, {**RULES, "contributions": [rule]}, actor="test")
        self.m = self.s.m

    def propose(self, amount="30", owed="fines", by=3, member=0):
        return propose_waiver(self.m[by].id, self.s.fund.id, self.m[member].id, owed=owed, amount=amount,
                              reason="Hospital stay")

    def test_the_member_it_is_for_and_the_proposer_may_not_approve(self):
        w = self.propose()
        self.assertEqual({a.id for a in eligible_waiver_approvers(w.id)}, {self.m[1].id, self.m[2].id})
        with self.assertRaisesMessage(GovernanceError, "cannot approve a waiver for themselves"):
            decide_waiver(w.id, self.m[0].id, approve=True)
        with self.assertRaisesMessage(GovernanceError, "only designated approvers approve waivers"):
            decide_waiver(w.id, self.m[3].id, approve=True)  # nor may the proposer, under these rules

    def test_an_approved_fines_waiver_lowers_what_is_owed_and_moves_no_money(self):
        w = self.propose()
        decide_waiver(w.id, self.m[1].id, approve=True)
        self.assertEqual(decide_waiver(w.id, self.m[1].id, approve=True).approvals, 1)  # a repeat is a no-op
        with self.assertRaisesMessage(GovernanceError, "cannot be changed"):
            decide_waiver(w.id, self.m[1].id, approve=False)
        self.assertEqual(decide_waiver(w.id, self.m[2].id, approve=True).status, "approved")
        as_of = timezone.localdate() + timedelta(days=20)  # three weeks missed: fines of 150
        s = member_standing(self.m[0].id, self.s.fund.id, as_of=as_of)
        self.assertEqual((s.standing.fines_total, s.fines_waived, s.fines_owed),
                         (Money("150"), Money("30"), Money("120")))
        self.assertEqual(s.standing.arrears, Money("3000"))  # a fines waiver forgives no contribution
        self.assertEqual(fund_position(self.fines.id).cash, Money("0"))
        with self.assertRaises(DatabaseError), transaction.atomic():
            Waiver.objects.filter(pk=w.id).update(amount="1")  # decided once, never edited

    def test_a_waiver_needs_a_fund_with_a_rule_and_can_be_cancelled(self):
        with self.assertRaisesMessage(GovernanceError, "no contribution rule"):
            propose_waiver(self.m[3].id, self.fines.id, self.m[0].id, owed="fines", amount="10", reason="x")
        w = self.propose()
        self.assertEqual(cancel_waiver(w.id, self.m[3].id).status, "cancelled")
        with self.assertRaisesMessage(GovernanceError, "already cancelled"):
            decide_waiver(w.id, self.m[1].id, approve=True)
