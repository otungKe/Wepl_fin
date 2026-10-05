"""Deciding a move between funds (ADR-0024): proposed only between the
group's own open funds and only for money its owners hold, decided like a
payout, and never edited or deleted afterwards."""
from django.db import DatabaseError, transaction
from django.test import TestCase

from contexts.communities.public import CommunityError, close_fund, open_fund
from contexts.governance.infrastructure.models import FundTransfer
from contexts.governance.public import (GovernanceError, TransferStatus, cancel_fund_transfer, decide_fund_transfer,
                                        eligible_transfer_approvers, fund_transfer, propose_fund_transfer)
from simulators.custodian_bank import bank
from tests.scenario import Scenario

N = "0012345678901"


class FundTransferDecisionTests(TestCase):
    def setUp(self):
        self.s = Scenario()
        with self.s.acting():
            self.welfare = open_fund(self.s.group.id, name="Welfare", code="WEL", actor="test")
        bank.deposit(N, "1000", msisdn="254712000001", name="WANJIKU K")
        bank.deposit(N, "500", msisdn="254733999999", name="STRANGER")  # unattributed: nobody's yet
        self.s.sync()
        self.enterContext(self.s.acting())
        self.m = self.s.m

    def propose(self, amount="100", *, by=3, frm=None, to=None, source="pro_rata", member=None, key=None):
        return propose_fund_transfer(self.m[by].id, (frm or self.s.fund).id, (to or self.welfare).id, amount=amount,
                                     source=source, member_id=member.id if member else None, reason="Top up",
                                     request_key=key)

    def test_refusals(self):
        cases = [
            ("two different funds", dict(to=self.s.fund)),
            ("Name a member exactly when", dict(source="member")),
            ("Name a member exactly when", dict(member=self.m[0])),
            ("amount above zero", dict(amount="0")),
            ("hold only KES 1,000.00", dict(amount="1200")),  # the unattributed 500 is nobody's to move
            ("hold only KES 0.00", dict(source="member", member=self.m[1])),
            ("hold only KES 0.00", dict(source="retained")),
        ]
        for message, kw in cases:
            with self.subTest(message), self.assertRaisesMessage(GovernanceError, message):
                self.propose(**kw)
        self.assertEqual(FundTransfer.objects.count(), 0)

    def test_a_closed_fund_takes_no_transfer(self):
        empty = open_fund(self.s.group.id, name="Old", actor="test")
        close_fund(empty.id, actor="test")
        with self.assertRaisesMessage(GovernanceError, "Old is closed"):
            self.propose(to=empty)

    def test_decided_like_a_payout_proposer_and_owner_excluded(self):
        with self.assertRaisesMessage(GovernanceError, "Not enough eligible approvers"):
            self.propose(source="member", member=self.m[0], by=1)  # leaves one designated approver of the two needed
        t = self.propose(source="member", member=self.m[0], by=3)
        self.assertEqual({a.id for a in eligible_transfer_approvers(t.id)}, {self.m[1].id, self.m[2].id})
        with self.assertRaisesMessage(GovernanceError, "cannot approve a transfer for themselves"):
            decide_fund_transfer(t.id, self.m[0].id, approve=True)
        with self.assertRaisesMessage(GovernanceError, "only designated approvers approve transfers"):
            decide_fund_transfer(t.id, self.m[4].id, approve=True)

    def test_approval_rejection_and_votes_that_cannot_change(self):
        t = self.propose()
        decide_fund_transfer(t.id, self.m[0].id, approve=True)
        self.assertEqual(decide_fund_transfer(t.id, self.m[0].id, approve=True).approvals, 1)  # a resent vote
        with self.assertRaisesMessage(GovernanceError, "cannot be changed"):
            decide_fund_transfer(t.id, self.m[0].id, approve=False)
        self.assertEqual(decide_fund_transfer(t.id, self.m[1].id, approve=True).status, TransferStatus.APPROVED)
        with self.assertRaisesMessage(GovernanceError, "already approved"):
            decide_fund_transfer(t.id, self.m[2].id, approve=True)
        r = self.propose()
        decide_fund_transfer(r.id, self.m[0].id, approve=False)
        self.assertEqual(decide_fund_transfer(r.id, self.m[1].id, approve=False).status, TransferStatus.REJECTED)

    def test_cancel(self):
        t = self.propose()
        with self.assertRaisesMessage(GovernanceError, "Only the proposer"):
            cancel_fund_transfer(t.id, self.m[4].id)
        self.assertEqual(cancel_fund_transfer(t.id, self.m[3].id).status, TransferStatus.CANCELLED)

    def test_a_retried_request_returns_the_first_transfer(self):
        first = self.propose(key="k1")
        self.assertEqual(self.propose(key="k1").id, first.id)
        self.propose(key="k2")
        self.assertEqual(FundTransfer.objects.count(), 2)
        with self.assertRaisesMessage(GovernanceError, "someone else's"):
            self.propose(key="k1", by=4)

    def test_neither_fund_closes_while_a_transfer_is_undecided(self):
        t = self.propose()
        with self.assertRaises(CommunityError):
            close_fund(self.welfare.id, actor="test")
        cancel_fund_transfer(t.id, self.m[3].id)
        self.assertEqual(close_fund(self.welfare.id, actor="test").status, "closed")

    def test_the_database_keeps_a_transfer_as_decided(self):
        t = self.propose()
        cancel_fund_transfer(t.id, self.m[3].id)
        for write in (lambda: FundTransfer.objects.filter(pk=t.id).update(amount=5),
                      lambda: FundTransfer.objects.filter(pk=t.id).update(status="open"),
                      lambda: FundTransfer.objects.filter(pk=t.id).update(status="booked", out_entry_id=1,
                                                                         in_entry_id=2),
                      lambda: FundTransfer.objects.filter(pk=t.id).delete()):
            with self.assertRaises(DatabaseError), transaction.atomic():
                write()
        self.assertEqual(fund_transfer(t.id).status, TransferStatus.CANCELLED)
