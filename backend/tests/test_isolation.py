"""A group is the data-isolation boundary (ADR-0005): nothing done in one
group's name may touch another group's money or decisions."""
from django.test import TestCase

from contexts.custody.infrastructure.models import StatementLine
from contexts.custody.public import CustodyError, attribute_payment, explain_outflow
from contexts.governance.infrastructure.models import Mandate
from contexts.governance.public import GovernanceError, decide, propose_withdrawal
from simulators.im_bank import bank
from tests.scenario import Scenario


class CrossGroupTests(TestCase):
    def setUp(self):
        self.a = Scenario("Group A", account="A1")
        self.b = Scenario("Group B", account="B1", people=[("0722000001", "B1", "chair"), ("0722000002", "B2", "treasurer"),
                                                          ("0722000003", "B3", "secretary")])
        for m in self.a.m:
            bank.deposit("A1", "1000", msisdn=m.msisdn, name="X")
        bank.deposit("A1", "50", msisdn="0733000000", name="STRANGER")
        self.a.sync()

    def test_cannot_attribute_a_payment_to_another_groups_member(self):
        line = StatementLine.objects.get(amount=50)
        with self.assertRaisesMessage(CustodyError, "another group"):
            attribute_payment(line.pk, self.b.m[0].id, actor="b-treasurer")

    def test_cannot_explain_an_outflow_with_another_groups_mandate(self):
        bank.withdraw("A1", "100", narration="ATM")
        self.a.sync()
        bank.deposit("B1", "1000", msisdn=self.b.m[0].msisdn, name="X")
        self.b.sync()
        foreign = Mandate.objects.get(reference=self.b.approve("100", proposer=self.b.m[1]))
        line = StatementLine.objects.get(amount=100, kind="withdrawal")
        with self.assertRaisesMessage(CustodyError, "this fund"):
            explain_outflow(line.pk, foreign.pk, actor="x")

    def test_cannot_propose_on_or_vote_in_another_group(self):
        with self.assertRaisesMessage(GovernanceError, "another group"):
            propose_withdrawal(self.b.m[1].id, self.a.fund.id, amount="10", purpose="x", payee_name="x",
                               payee_account="0799000000")
        p = propose_withdrawal(self.a.m[1].id, self.a.fund.id, amount="10", purpose="x", payee_name="x",
                               payee_account="0799000000")
        with self.assertRaisesMessage(GovernanceError, "not a member of this group"):
            decide(p.id, self.b.m[0].id, approve=True)

    def test_a_foreign_mandate_reference_never_authorises_a_payout(self):
        bank.deposit("B1", "1000", msisdn=self.b.m[0].msisdn, name="X")
        self.b.sync()
        ref = self.b.approve("200", proposer=self.b.m[1])
        bank.withdraw("A1", "200", narration=f"PAY {ref}")
        self.a.sync()
        line = StatementLine.objects.get(amount=200)
        self.assertEqual(line.resolutions.get().outcome, "unmatched")
        self.assertEqual(Mandate.objects.get(reference=ref).status, "issued")
