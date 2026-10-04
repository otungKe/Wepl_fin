"""Defence in depth between groups (ADR-0005, ADR-0010). Each group is its own
tenant, so row-level security is what keeps groups apart (test_tenancy.py).
These tests deliberately widen row-level security with a declared
cross-tenant operation, so every record is visible, and show that the
application checks still refuse to mix one group's members, funds and
mandates with another's. Nothing may be written either way."""
from django.test import TestCase

from contexts.custody.infrastructure.models import LineResolution, StatementLine
from contexts.custody.public import CustodyError, attribute_payment, explain_outflow
from contexts.governance.infrastructure.models import Approval, Mandate, Proposal
from contexts.governance.public import GovernanceError, decide, propose_withdrawal
from contexts.tenancy.public import cross_tenant
from simulators.custodian_bank import bank
from tests.scenario import SIGNATORY, Scenario


class CrossGroupTests(TestCase):
    def setUp(self):
        self.a = Scenario("Group A", account="A1")
        self.b = Scenario("Group B", account="B1", people=[("0722000001", "B1", "Chair", SIGNATORY),
                                                           ("0722000002", "B2", "Treasurer", SIGNATORY),
                                                           ("0722000003", "B3", "Secretary", SIGNATORY)])
        for m in self.a.m:
            bank.deposit("A1", "1000", msisdn=m.msisdn, name="X")
        bank.deposit("A1", "50", msisdn="0733000000", name="STRANGER")
        bank.withdraw("A1", "100", narration="ATM")
        self.a.sync()
        bank.deposit("B1", "1000", msisdn=self.b.m[0].msisdn, name="X")
        self.b.sync()
        self.b_ref = self.b.approve("100")
        with self.a.acting():
            self.a_stranger = StatementLine.objects.get(amount=50).pk
            self.a_atm = StatementLine.objects.get(amount=100, kind="withdrawal").pk
            self.a_proposal = propose_withdrawal(self.a.m[1].id, self.a.fund.id, amount="10", purpose="x",
                                                 payee_name="x", payee_account="0799000000").id

    def widened(self):
        return cross_tenant("defence-in-depth test: row-level security deliberately widened", actor="test")

    def assert_nothing_written(self):
        with self.widened():
            self.assertEqual(LineResolution.objects.filter(line_id__in=[self.a_stranger, self.a_atm],
                                                           outcome__in=["attributed", "explained"]).count(), 0)
            self.assertEqual(Approval.objects.filter(proposal_id=self.a_proposal).count(), 0)
            self.assertEqual(Proposal.objects.filter(fund_id=self.a.fund.id).count(), 1)
            self.assertEqual(Mandate.objects.get(reference=self.b_ref).status, "issued")

    def test_cannot_attribute_a_payment_to_another_groups_member(self):
        with self.widened(), self.assertRaisesMessage(CustodyError, "not in this group"):
            attribute_payment(self.a_stranger, self.b.m[0].id, by=self.a.m[1].id)
        self.assert_nothing_written()

    def test_another_groups_corrector_cannot_correct(self):
        with self.widened(), self.assertRaisesMessage(CustodyError, "not a member of this group"):
            attribute_payment(self.a_stranger, self.a.m[4].id, by=self.b.m[1].id)
        self.assert_nothing_written()

    def test_cannot_explain_an_outflow_with_another_groups_mandate(self):
        with self.widened():
            foreign = Mandate.objects.get(reference=self.b_ref).pk
            with self.assertRaisesMessage(CustodyError, "this group's"):
                explain_outflow(self.a_atm, foreign, by=self.a.m[0].id)
        self.assert_nothing_written()

    def test_cannot_propose_on_or_vote_in_another_group(self):
        with self.widened():
            with self.assertRaisesMessage(GovernanceError, "another group"):
                propose_withdrawal(self.b.m[1].id, self.a.fund.id, amount="10", purpose="x", payee_name="x",
                                   payee_account="0799000000")
            with self.assertRaisesMessage(GovernanceError, "not a member of this group"):
                decide(self.a_proposal, self.b.m[0].id, approve=True)
        self.assert_nothing_written()

    def test_a_foreign_mandate_reference_never_authorises_a_payout(self):
        bank.withdraw("A1", "100", narration=f"PAY {self.b_ref}")
        self.a.sync()
        with self.a.acting():
            line = StatementLine.objects.filter(amount=100, kind="withdrawal").latest("id")
            self.assertEqual(line.resolutions.get().outcome, "unmatched")
        self.assert_nothing_written()
