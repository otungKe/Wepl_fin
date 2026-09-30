from django.db import transaction
from django.db.utils import DatabaseError
from django.test import TestCase

from governance import services as gov
from governance.models import Approval, Constitution, Mandate, Proposal

from .factories import approve_withdrawal, make_group


class GovernanceTests(TestCase):
    def setUp(self):
        self.group, self.fund, self.m, self.ea = make_group()
        self.chair, self.treasurer, self.secretary, self.member4, self.member5 = self.m

    def propose(self, amount, proposer=None, **kw):
        kw.setdefault("payee_name", "Supplier")
        kw.setdefault("payee_account", "0799000000")
        return gov.propose_withdrawal(proposer or self.treasurer, self.fund, amount=amount, purpose="x", **kw)

    def test_small_withdrawal_needs_two_officials(self):
        p = self.propose("5000")
        self.assertEqual((p.approvers, p.required_approvals), ("officials", 2))
        gov.decide(p, self.chair, approve=True)
        p.refresh_from_db()
        self.assertEqual(p.status, Proposal.Status.OPEN)
        gov.decide(p, self.secretary, approve=True)
        p.refresh_from_db()
        self.assertEqual(p.status, Proposal.Status.APPROVED)
        self.assertTrue(p.mandate.reference.startswith("WM"))

    def test_ordinary_member_cannot_approve_officials_tier(self):
        p = self.propose("5000")
        with self.assertRaises(gov.GovernanceError):
            gov.decide(p, self.member4, approve=True)

    def test_proposer_cannot_approve_own_request(self):
        p = self.propose("5000")
        with self.assertRaises(gov.GovernanceError):
            gov.decide(p, self.treasurer, approve=True)

    def test_payee_cannot_approve_payment_to_themselves(self):
        p = self.propose("50000", payee_account=self.chair.person.msisdn)
        with self.assertRaises(gov.GovernanceError):
            gov.decide(p, self.chair, approve=True)

    def test_large_withdrawal_needs_three_members(self):
        p = self.propose("50000")
        self.assertEqual((p.approvers, p.required_approvals), ("members", 3))
        for voter in (self.chair, self.member4, self.member5):
            gov.decide(p, voter, approve=True)
        p.refresh_from_db()
        self.assertEqual(p.status, Proposal.Status.APPROVED)

    def test_rejected_when_threshold_becomes_impossible(self):
        p = self.propose("5000")  # eligible: chair, secretary; needs 2
        gov.decide(p, self.chair, approve=False)
        p.refresh_from_db()
        self.assertEqual(p.status, Proposal.Status.REJECTED)
        self.assertFalse(Mandate.objects.filter(proposal=p).exists())

    def test_cannot_vote_twice_or_after_decision(self):
        p = self.propose("5000")
        gov.decide(p, self.chair, approve=True)
        with self.assertRaises(gov.GovernanceError):
            gov.decide(p, self.chair, approve=True)
        gov.decide(p, self.secretary, approve=True)
        with self.assertRaises(gov.GovernanceError):
            gov.decide(p, self.member4, approve=True)

    def test_not_enough_approvers_is_refused(self):
        with self.assertRaises(gov.GovernanceError):
            self.propose("5000", proposer=self.chair, charged_member=self.secretary)

    def test_mandate_claimed_only_once(self):
        mandate = approve_withdrawal(self.m, self.fund, "1000")
        self.assertTrue(gov.claim_mandate(mandate.pk, line_id=1, when=mandate.issued_at))
        self.assertFalse(gov.claim_mandate(mandate.pk, line_id=2, when=mandate.issued_at))

    def test_constitution_versions_and_immutability(self):
        gov.decide(self.propose("5000"), self.chair, approve=True)
        c2 = gov.adopt_constitution(self.group, {"approvals": [{"up_to": None, "approvers": "officials",
                                                                "required": 1}]}, actor="t")
        self.assertEqual(c2.version, 2)
        self.assertEqual(gov.current_constitution(self.group).pk, c2.pk)
        with self.assertRaisesMessage(DatabaseError, "append-only"):
            with transaction.atomic():
                Constitution.objects.filter(pk=c2.pk).update(rules={})
        with self.assertRaisesMessage(DatabaseError, "append-only"):
            with transaction.atomic():
                Approval.objects.all().delete()

    def test_invalid_rules_rejected(self):
        for rules in ({"approvals": []},
                      {"approvals": [{"up_to": "10", "approvers": "officials", "required": 1}]},
                      {"approvals": [{"up_to": None, "approvers": "anyone", "required": 1}]},
                      {"approvals": [{"up_to": None, "approvers": "members", "required": 1}],
                       "interest": "burn"}):
            with self.assertRaises(gov.GovernanceError):
                gov.validate_rules(rules)
