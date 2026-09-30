from django.test import SimpleTestCase

from contexts.governance.domain.lifecycle import (MANDATE_TRANSITIONS, PROPOSAL_TRANSITIONS, InvalidTransition,
                                                  MandateStatus, ProposalStatus, ensure)
from contexts.governance.domain.mandate import MANDATE_REFERENCE, new_reference
from contexts.governance.domain.rules import ApproverSet, ConstitutionRules, RulesError
from contexts.governance.domain.voting import ProposalTerms, Voter, ineligibility, tally
from contexts.shared_kernel.money import Money

RULES = {"approvals": [{"up_to": "20000", "approvers": "officials", "required": 2},
                       {"up_to": None, "approvers": "members", "required": 3}]}


class RulesTests(SimpleTestCase):
    def test_tiers_by_amount(self):
        r = ConstitutionRules.parse(RULES)
        self.assertEqual(r.tier_for(Money("20000")).approvers, ApproverSet.OFFICIALS)
        self.assertEqual(r.tier_for(Money("20000.01")).required, 3)

    def test_round_trips(self):
        r = ConstitutionRules.parse(RULES)
        self.assertEqual(ConstitutionRules.parse(r.to_dict()), r)

    def test_invalid_rules_rejected(self):
        for raw in ({"approvals": []},
                    {"approvals": [{"up_to": "10", "approvers": "officials", "required": 1}]},
                    {"approvals": [{"up_to": None, "approvers": "anyone", "required": 1}]},
                    {"approvals": [{"up_to": None, "approvers": "members", "required": 0}]},
                    {"approvals": [{"up_to": "10", "approvers": "members", "required": 1},
                                   {"up_to": "5", "approvers": "members", "required": 1},
                                   {"up_to": None, "approvers": "members", "required": 1}]},
                    {**RULES, "interest": "burn"}, {**RULES, "mandate_valid_days": 0}):
            with self.assertRaises(RulesError):
                ConstitutionRules.parse(raw)


class VotingTests(SimpleTestCase):
    terms = ProposalTerms(group_id=1, proposer_id=2, charged_member_id=4, payee_account="0712000009",
                          approvers=ApproverSet.OFFICIALS, required=2, allow_self_approval=False)

    def voter(self, mid=1, **kw):
        base = dict(membership_id=mid, group_id=1, active=True, official=True, msisdn="254712000001")
        return Voter(**{**base, **kw})

    def test_eligible_official(self):
        self.assertIsNone(ineligibility(self.voter(), self.terms))

    def test_reasons_for_refusal(self):
        cases = {"another group": self.voter(group_id=2), "active": self.voter(active=False),
                 "officials": self.voter(official=False), "request they made": self.voter(mid=2),
                 "charged to themselves": self.voter(mid=4), "payment to themselves": self.voter(msisdn="254712000009")}
        for expected, voter in cases.items():
            self.assertIn(expected.split()[-1], ineligibility(voter, self.terms))

    def test_self_approval_only_when_the_constitution_allows(self):
        allowed = ProposalTerms(**{**self.terms.__dict__, "allow_self_approval": True})
        self.assertIsNone(ineligibility(self.voter(mid=2), allowed))

    def test_tally(self):
        self.assertEqual(tally(required=2, approvals=2, declines=0, eligible=3), ProposalStatus.APPROVED)
        self.assertEqual(tally(required=2, approvals=1, declines=2, eligible=3), ProposalStatus.REJECTED)
        self.assertEqual(tally(required=2, approvals=1, declines=1, eligible=3), ProposalStatus.OPEN)


class LifecycleTests(SimpleTestCase):
    def test_only_open_proposals_and_issued_mandates_move(self):
        ensure(PROPOSAL_TRANSITIONS, ProposalStatus.OPEN, ProposalStatus.APPROVED)
        ensure(MANDATE_TRANSITIONS, MandateStatus.ISSUED, MandateStatus.EXECUTED)
        for current, new in ((ProposalStatus.APPROVED, ProposalStatus.CANCELLED),
                             (ProposalStatus.REJECTED, ProposalStatus.APPROVED)):
            with self.assertRaises(InvalidTransition):
                ensure(PROPOSAL_TRANSITIONS, current, new)
        for current in (MandateStatus.EXECUTED, MandateStatus.EXPIRED, MandateStatus.CANCELLED):
            with self.assertRaises(InvalidTransition):
                ensure(MANDATE_TRANSITIONS, current, MandateStatus.EXECUTED)

    def test_references_are_recognisable(self):
        for _ in range(50):
            self.assertRegex(f"PAY {new_reference()} X", MANDATE_REFERENCE)
