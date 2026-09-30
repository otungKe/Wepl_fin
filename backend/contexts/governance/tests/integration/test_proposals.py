from django.db import transaction
from django.db.utils import DatabaseError
from django.test import TestCase

from contexts.audit.public import history
from contexts.communities.public import Role, add_member, create_group
from contexts.governance.infrastructure.models import Approval, Constitution, Mandate
from contexts.governance.public import (GovernanceError, InvalidTransition, MandateStatus, ProposalStatus,
                                        adopt_constitution, cancel_proposal, decide, execute_mandate,
                                        expire_mandates, propose_withdrawal)
from contexts.shared_kernel.money import Money

RULES = {"approvals": [{"up_to": "20000", "approvers": "officials", "required": 2},
                       {"up_to": None, "approvers": "members", "required": 3}]}


class ProposalTests(TestCase):
    def setUp(self):
        self.group, self.fund = create_group("G", actor="t")
        adopt_constitution(self.group.id, RULES, actor="t")
        roles = [Role.CHAIR, Role.TREASURER, Role.SECRETARY, Role.MEMBER, Role.MEMBER]
        self.chair, self.treasurer, self.secretary, self.m4, self.m5 = (
            add_member(self.group.id, msisdn=f"07120000{i:02d}", name=f"P{i}", role=r, actor="t")
            for i, r in enumerate(roles, 1))

    def propose(self, amount="5000", proposer=None, **kw):
        kw.setdefault("payee_name", "Supplier")
        kw.setdefault("payee_account", "0799000000")
        return propose_withdrawal((proposer or self.treasurer).id, self.fund.id, amount=amount, purpose="x", **kw)

    def test_two_officials_approve_and_a_mandate_is_issued(self):
        p = self.propose()
        self.assertEqual(p.required_approvals, 2)
        self.assertEqual(decide(p.id, self.chair.id, approve=True).status, ProposalStatus.OPEN)
        p = decide(p.id, self.secretary.id, approve=True)
        self.assertEqual(p.status, ProposalStatus.APPROVED)
        self.assertRegex(p.mandate_reference, r"^WM")
        actions = [h["action"] for h in history(target_type="proposal", target_id=p.id)]
        self.assertEqual(actions, ["proposal.created", "proposal.decided", "proposal.decided", "proposal.approved"])

    def test_large_withdrawal_needs_three_members(self):
        p = self.propose("50000")
        self.assertEqual(p.required_approvals, 3)
        for voter in (self.chair, self.m4, self.m5):
            p = decide(p.id, voter.id, approve=True)
        self.assertEqual(p.status, ProposalStatus.APPROVED)

    def test_unauthorised_voters_are_refused(self):
        p = self.propose()
        for voter, why in ((self.m4, "officials"), (self.treasurer, "request they made")):
            with self.assertRaisesMessage(GovernanceError, why):
                decide(p.id, voter.id, approve=True)
        big = self.propose("50000", payee_account=self.chair.msisdn)
        with self.assertRaisesMessage(GovernanceError, "payment to themselves"):
            decide(big.id, self.chair.id, approve=True)

    def test_voter_from_another_group_is_refused(self):
        other, _ = create_group("Other", actor="t")
        outsider = add_member(other.id, msisdn="0712999999", name="X", role=Role.CHAIR, actor="t")
        with self.assertRaisesMessage(GovernanceError, "not a member of this group"):
            decide(self.propose().id, outsider.id, approve=True)

    def test_repeated_vote_is_idempotent_but_cannot_change(self):
        p = self.propose()
        decide(p.id, self.chair.id, approve=True)
        decide(p.id, self.chair.id, approve=True, source="sms")
        self.assertEqual(Approval.objects.count(), 1)
        with self.assertRaisesMessage(GovernanceError, "cannot be changed"):
            decide(p.id, self.chair.id, approve=False)

    def test_retried_submission_returns_the_first_proposal(self):
        a = self.propose(request_key="req-1")
        b = self.propose(request_key="req-1")
        self.assertEqual(a.id, b.id)
        with self.assertRaisesMessage(GovernanceError, "someone else's"):
            self.propose(request_key="req-1", proposer=self.chair)

    def test_rejected_when_threshold_becomes_impossible(self):
        p = decide(self.propose().id, self.chair.id, approve=False)
        self.assertEqual(p.status, ProposalStatus.REJECTED)
        with self.assertRaisesMessage(GovernanceError, "already rejected"):
            decide(p.id, self.secretary.id, approve=True)

    def test_not_enough_eligible_approvers(self):
        with self.assertRaisesMessage(GovernanceError, "Not enough eligible"):
            self.propose(proposer=self.chair, charged_member_id=self.secretary.id)

    def test_cancel_only_while_open_and_only_by_proposer_or_official(self):
        p = self.propose()
        with self.assertRaisesMessage(GovernanceError, "Only the proposer"):
            cancel_proposal(p.id, self.m4.id)
        cancel_proposal(p.id, self.treasurer.id)
        with self.assertRaises(InvalidTransition):
            cancel_proposal(p.id, self.chair.id)

    def test_mandate_executes_once_and_expires(self):
        p = decide(decide(self.propose().id, self.chair.id, approve=True).id, self.secretary.id, approve=True)
        m = Mandate.objects.get(reference=p.mandate_reference)
        self.assertTrue(execute_mandate(m.pk, line_id=1, when=m.issued_at))
        self.assertFalse(execute_mandate(m.pk, line_id=2, when=m.issued_at))
        p2 = decide(decide(self.propose("100").id, self.chair.id, approve=True).id, self.secretary.id, approve=True)
        self.assertEqual(expire_mandates(now=m.expires_at + (m.expires_at - m.issued_at)), 1)
        self.assertEqual(Mandate.objects.get(reference=p2.mandate_reference).status, MandateStatus.EXPIRED)
        self.assertEqual(Mandate.objects.get(pk=m.pk).status, MandateStatus.EXECUTED)

    def test_constitution_versions_are_immutable(self):
        decide(self.propose().id, self.chair.id, approve=True)
        self.assertEqual(adopt_constitution(self.group.id, RULES, actor="t"), 2)
        for action in (lambda: Constitution.objects.update(rules={}), lambda: Approval.objects.all().delete()):
            with self.assertRaisesMessage(DatabaseError, "append-only"):
                with transaction.atomic():
                    action()

    def test_amounts_are_money(self):
        with self.assertRaises(Exception):
            self.propose(amount=100.5)
        self.assertEqual(self.propose(amount="100.5").amount, Money("100.50"))
