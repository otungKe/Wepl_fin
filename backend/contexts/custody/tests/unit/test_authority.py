from unittest import TestCase

from contexts.custody.domain.authority import Actor, pair_refusal, refusal


def actor(mid=1, group=10, *, active=True, may_correct=True):
    return Actor(membership_id=mid, group_id=group, active=active, may_correct=may_correct)


class RefusalTests(TestCase):
    def test_an_active_member_granted_correct_records_may_correct(self):
        self.assertIsNone(refusal(actor(), group_id=10, beneficiary_ids=frozenset({2})))

    def test_everyone_else_is_refused(self):
        cases = {"not a member of this group": actor(group=11), "not an active member": actor(active=False),
                 "not been granted correct_records": actor(may_correct=False)}
        for reason, who in cases.items():
            with self.subTest(reason):
                self.assertIn(reason, refusal(who, group_id=10))

    def test_no_correction_in_ones_own_favour(self):
        self.assertIn("own favour", refusal(actor(mid=1), group_id=10, beneficiary_ids=frozenset({1})))

    def test_opening_balances_need_two_different_holders(self):
        self.assertIsNone(pair_refusal(actor(1), actor(2), group_id=10))
        self.assertIn("same member", pair_refusal(actor(1), actor(1), group_id=10))
        self.assertIn("not been granted", pair_refusal(actor(1), actor(2, may_correct=False), group_id=10))
