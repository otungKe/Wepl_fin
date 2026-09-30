"""A member code is a stable business identifier (ADR-0012): handed out once,
never freed, never re-pointed."""
from django.db import DatabaseError, transaction
from django.test import TestCase

from contexts.audit.public import history
from contexts.communities.infrastructure.models import Group, Membership
from contexts.communities.public import (CommunityError, add_member, create_group, leave_group, members,
                                         set_title)
from contexts.governance.public import Capability, capabilities_of, grant
from tests.scenario import act_for_new_tenant


class MembershipTests(TestCase):
    def setUp(self):
        act_for_new_tenant(self)
        self.group, _ = create_group("G", actor="t")

    def add(self, n, **kw):
        return add_member(self.group.id, msisdn=f"07120000{n:02d}", name=f"P{n}", actor="t", **kw)

    def refused_by_the_database(self, write):
        with self.assertRaises(DatabaseError), transaction.atomic():
            write()

    def test_codes_come_from_the_groups_counter_not_a_count(self):
        self.assertEqual([self.add(n).code for n in (1, 2)], ["M01", "M02"])
        Group.objects.filter(pk=self.group.id).update(last_member_sequence=41)
        self.assertEqual(self.add(3).code, "M42")

    def test_the_counter_never_goes_back(self):
        self.add(1)
        self.refused_by_the_database(lambda: Group.objects.filter(pk=self.group.id).update(last_member_sequence=0))

    def test_leaving_keeps_the_code_and_a_returning_member_gets_a_new_one(self):
        first = self.add(1)
        self.add(2)
        left = leave_group(first.id, actor="t")
        self.assertEqual((left.status, left.code), ("left", "M01"))
        back = self.add(1)
        self.assertNotEqual(back.id, first.id)
        self.assertEqual(back.code, "M03")
        self.assertEqual([m.code for m in members(self.group.id)], ["M02", "M03"])
        self.assertEqual([m.code for m in members(self.group.id, active_only=False)], ["M01", "M02", "M03"])

    def test_first_membership(self):
        m = self.add(1, title="Treasurer")
        self.assertEqual((m.code, m.status, m.title), ("M01", "active", "Treasurer"))

    def test_one_active_spell_per_person(self):
        first = self.add(1)
        with self.assertRaisesMessage(CommunityError, "already an active member"):
            self.add(1)
        self.refused_by_the_database(lambda: Membership.objects.create(
            group_id=self.group.id, person_id=first.person_id, member_code="M77"))

    def test_repeated_leaving_and_returning(self):
        """Every return is a new spell with a new code, for the same person."""
        spells = []
        for cycle in range(3):
            spells.append(self.add(1))
            self.add(10 + cycle)  # someone else joins in between
            leave_group(spells[-1].id, actor="t")
        spells.append(self.add(1))
        self.assertEqual([s.code for s in spells], ["M01", "M03", "M05", "M07"])
        self.assertEqual(len({s.id for s in spells}), 4)
        self.assertEqual({s.person_id for s in spells}, {spells[0].person_id})
        mine = [m for m in members(self.group.id, active_only=False) if m.person_id == spells[0].person_id]
        self.assertEqual([(m.code, m.status) for m in mine],
                         [("M01", "left"), ("M03", "left"), ("M05", "left"), ("M07", "active")])

    def test_a_returning_person_keeps_their_identity_even_under_another_name(self):
        first = self.add(1)
        leave_group(first.id, actor="t")
        back = add_member(self.group.id, msisdn="+254712000001", name="Another spelling", actor="t")
        self.assertEqual((back.person_id, back.name), (first.person_id, first.name))

    def test_leaving_is_final_and_audited(self):
        m = self.add(1)
        leave_group(m.id, actor="t")
        with self.assertRaisesMessage(CommunityError, "already ended"):
            leave_group(m.id, actor="t")
        self.refused_by_the_database(lambda: Membership.objects.filter(pk=m.id).update(status="active"))
        self.assertIn("member.left", [e["action"] for e in history(target_type="membership", target_id=m.id)])

    def test_a_member_who_left_holds_no_capability(self):
        m = self.add(1)
        grant(m.id, Capability.CORRECT_RECORDS, actor="t")
        leave_group(m.id, actor="t")
        self.assertEqual(capabilities_of(m.id), frozenset())

    def test_memberships_are_never_deleted_or_re_pointed(self):
        a, b = self.add(1), self.add(2)
        self.refused_by_the_database(lambda: Membership.objects.filter(pk=a.id).delete())
        self.refused_by_the_database(lambda: Membership.objects.filter(pk=a.id).update(member_code="M99"))
        self.refused_by_the_database(lambda: Membership.objects.filter(pk=a.id).update(person_id=b.person_id))

    def test_a_title_changes_without_changing_authority_and_history_is_kept(self):
        m = self.add(1, title="Treasurer")
        m = set_title(m.id, "  Chair  person ", actor="t")
        self.assertEqual(m.title, "Chair person")
        self.assertEqual(capabilities_of(m.id), frozenset())
        change = [e for e in history(target_type="membership", target_id=m.id)
                  if e["action"] == "member.title_changed"][0]
        self.assertEqual(change["data"], {"from": "Treasurer", "to": "Chair person"})
        set_title(m.id, None, actor="t")
        self.assertEqual(Membership.objects.get(pk=m.id).title, "")

    def test_an_overlong_title_is_refused(self):
        with self.assertRaisesMessage(CommunityError, "at most"):
            self.add(1, title="x" * 61)
