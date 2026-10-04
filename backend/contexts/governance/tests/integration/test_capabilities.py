"""What a member may do is what their group granted them, never their title
(ADR-0011)."""
from django.db import DatabaseError, transaction
from django.test import TestCase
from django.utils import timezone

from contexts.audit.public import history
from contexts.communities.infrastructure.models import Membership
from contexts.communities.public import add_member
from contexts.governance.infrastructure.models import CapabilityChange
from contexts.governance.public import (Capability, GovernanceError, adopt_constitution, cancel_proposal,
                                        capabilities_of, eligible_approvers, grant, holders, holds,
                                        propose_withdrawal, revoke)
from tests.scenario import act_for_new_group

RULES = {"approvals": [{"up_to": None, "approvers": "designated", "required": 1}], "leaver_balances": "frozen_at_leaving"}


class CapabilityTests(TestCase):
    def setUp(self):
        self.group, self.fund = act_for_new_group(self)
        adopt_constitution(self.group.id, RULES, actor="t")
        self.chair = add_member(self.group.id, msisdn="0712000001", name="Chair", title="Chair", actor="t")
        self.a = add_member(self.group.id, msisdn="0712000002", name="A", actor="t")
        self.b = add_member(self.group.id, msisdn="0712000003", name="B", actor="t")

    def propose(self, by):
        return propose_withdrawal(by.id, self.fund.id, amount="100", purpose="x", payee_name="S",
                                  payee_account="0799000000")

    def test_a_title_grants_nothing(self):
        self.assertEqual(self.chair.title, "Chair")
        self.assertEqual(capabilities_of(self.chair.id), frozenset())
        with self.assertRaisesMessage(GovernanceError, "Not enough eligible"):
            self.propose(self.a)

    def test_a_grant_is_what_makes_a_member_an_approver(self):
        grant(self.b.id, Capability.APPROVE_PAYOUT, actor="t")  # an untitled member
        self.assertEqual(holders(self.group.id, Capability.APPROVE_PAYOUT), [self.b.id])
        self.assertEqual([m.id for m in eligible_approvers(self.propose(self.a).id)], [self.b.id])

    def test_revoking_takes_the_capability_away_and_history_stays(self):
        grant(self.b.id, Capability.APPROVE_PAYOUT, actor="t")
        revoke(self.b.id, Capability.APPROVE_PAYOUT, actor="t")
        self.assertFalse(holds(self.b.id, Capability.APPROVE_PAYOUT))
        self.assertEqual(list(CapabilityChange.objects.values_list("granted", flat=True)), [True, False])
        actions = [e["action"] for e in history(target_type="membership", target_id=self.b.id)]
        self.assertIn("capability.granted", actions)
        self.assertIn("capability.revoked", actions)

    def test_repeating_a_grant_changes_nothing(self):
        grant(self.b.id, Capability.CORRECT_RECORDS, actor="t")
        grant(self.b.id, Capability.CORRECT_RECORDS, actor="t")
        self.assertEqual(CapabilityChange.objects.count(), 1)

    def test_capabilities_are_separate(self):
        grant(self.b.id, Capability.CORRECT_RECORDS, actor="t")
        self.assertEqual(capabilities_of(self.b.id), {Capability.CORRECT_RECORDS})
        self.assertFalse(holds(self.b.id, Capability.APPROVE_PAYOUT))

    def test_a_member_who_left_holds_nothing_and_cannot_be_granted(self):
        grant(self.b.id, Capability.APPROVE_PAYOUT, actor="t")
        Membership.objects.filter(pk=self.b.id).update(status="left", left_at=timezone.now())
        self.assertEqual(capabilities_of(self.b.id), frozenset())
        with self.assertRaisesMessage(GovernanceError, "active member"):
            grant(self.b.id, Capability.CORRECT_RECORDS, actor="t")

    def test_unknown_capabilities_are_refused(self):
        with self.assertRaisesMessage(GovernanceError, "Unknown capability"):
            grant(self.b.id, "chair", actor="t")

    def test_cancel_payout_lets_someone_other_than_the_proposer_cancel(self):
        grant(self.b.id, Capability.APPROVE_PAYOUT, actor="t")
        p = self.propose(self.a)
        with self.assertRaisesMessage(GovernanceError, "cancel_payout"):
            cancel_proposal(p.id, self.chair.id)  # a title does not let them cancel
        grant(self.chair.id, Capability.CANCEL_PAYOUT, actor="t")
        cancel_proposal(p.id, self.chair.id)

    def test_changes_are_append_only(self):
        grant(self.b.id, Capability.APPROVE_PAYOUT, actor="t")
        for write in (lambda: CapabilityChange.objects.update(granted=False),
                      lambda: CapabilityChange.objects.all().delete()):
            with self.assertRaises(DatabaseError), transaction.atomic():
                write()
