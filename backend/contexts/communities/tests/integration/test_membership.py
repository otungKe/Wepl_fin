"""A member code is a stable business identifier (ADR-0012): handed out once,
never freed, never re-pointed."""
from unittest import mock

from django.db import DatabaseError, transaction
from django.test import TestCase

from contexts.audit.public import history
from contexts.communities.infrastructure.models import Fund, Group, Membership
from contexts.communities.public import (CommunityError, add_member, create_group, leave_group, members,
                                         open_fund, set_title)
from contexts.governance.public import Capability, capabilities_of, grant
from contexts.identity.infrastructure.models import Person
from contexts.tenancy.public import TenancyError, cross_tenant, tenant
from tests.scenario import act_for_new_group


class MembershipTests(TestCase):
    def setUp(self):
        self.group, _ = act_for_new_group(self)

    def add(self, n, **kw):
        return add_member(self.group.id, msisdn=f"07120000{n:02d}", name=f"P{n}", actor="t", **kw)

    def refused_by_the_database(self, write):
        with self.assertRaises(DatabaseError), transaction.atomic():
            write()

    def test_only_joining_moves_the_counter(self):
        self.assertEqual([self.add(n).code for n in (1, 2)], ["M01", "M02"])
        for value in (0, 1, 3, 41):
            with self.subTest(value):
                self.refused_by_the_database(
                    lambda: Group.objects.filter(pk=self.group.id).update(last_member_sequence=value))
        self.assertEqual(self.add(3).code, "M03")

    def test_a_failed_join_consumes_no_code_and_a_retry_takes_it(self):
        self.add(1)
        with mock.patch("contexts.communities.application.memberships.record", side_effect=RuntimeError("audit down")):
            with self.assertRaises(RuntimeError):
                self.add(2)  # the membership was inserted, then the transaction rolled back
        self.assertEqual(Group.objects.get(pk=self.group.id).last_member_sequence, 1)
        self.assertFalse(Membership.objects.filter(member_code="M02").exists())
        self.assertEqual(self.add(2).code, "M02")  # never committed before, so not a reuse
        self.assertEqual(self.add(3).code, "M03")

    def test_a_refused_insert_leaves_the_counter_unchanged(self):
        first = self.add(1)
        self.refused_by_the_database(lambda: Membership.objects.create(  # a second active spell
            group_id=self.group.id, person_id=first.person_id, member_code="M02"))
        self.assertEqual(Group.objects.get(pk=self.group.id).last_member_sequence, 1)
        self.assertEqual(self.add(2).code, "M02")

    def test_an_unknown_or_foreign_group_is_a_community_error(self):
        with self.assertRaisesMessage(CommunityError, "Unknown group"):
            add_member(999999, msisdn="0712000001", name="P", actor="t")
        with self.assertRaisesMessage(CommunityError, "Unknown group"):
            open_fund(999999, name="Savings", actor="t")

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

    def test_an_ended_spells_title_is_history(self):
        m = self.add(1, title="Treasurer")
        leave_group(m.id, actor="t")
        with self.assertRaisesMessage(CommunityError, "has ended"):
            set_title(m.id, "Chair", actor="t")
        self.assertEqual(Membership.objects.get(pk=m.id).title, "Treasurer")

    def test_a_returning_member_starts_without_a_title(self):
        old = self.add(1, title="Treasurer")
        leave_group(old.id, actor="t")
        self.assertEqual(self.add(1).title, "")
        self.assertEqual(self.add(2, title="Chair").title, "Chair")

    def test_an_unknown_member_is_a_community_error(self):
        for use_case in (lambda: set_title(999999, "X", actor="t"), lambda: leave_group(999999, actor="t")):
            with self.subTest(use_case), self.assertRaisesMessage(CommunityError, "Unknown member"):
                use_case()

    def test_an_overlong_title_is_refused(self):
        with self.assertRaisesMessage(CommunityError, "at most"):
            self.add(1, title="x" * 61)


class DatabaseAllocatesCodesTests(TestCase):
    """PostgreSQL takes the next sequence on every insert, whoever inserts (ADR-0013)."""

    def setUp(self):
        self.group, _ = act_for_new_group(self)
        self.person = add_member(self.group.id, msisdn="0712000001", name="P1", actor="t").person_id

    def insert(self, code, msisdn="0712000002"):
        from contexts.identity.public import register_person
        person = register_person(msisdn, "X").id
        return Membership.objects.create(group_id=self.group.id, person_id=person, member_code=code)

    def test_a_direct_insert_must_take_the_next_code(self):
        for wrong in ("M01", "M03", "M99", "X02"):
            with self.subTest(wrong), self.assertRaises(DatabaseError), transaction.atomic():
                self.insert(wrong)
        self.assertEqual(self.insert("M02").member_code, "M02")
        self.assertEqual(Group.objects.get(pk=self.group.id).last_member_sequence, 2)

    def test_the_format_the_database_expects_is_the_domains(self):
        for n in range(2, 100):
            add_member(self.group.id, msisdn=f"0713{n:06d}", name="P", actor="t")
        self.assertEqual(add_member(self.group.id, msisdn="0712000003", name="P", actor="t").code, "M100")


class TenantBoundaryTests(TestCase):
    """A membership lives in its group's tenant, whoever writes it (review B1, B2)."""

    def setUp(self):
        self.a = create_group("A", actor="t")
        self.b = create_group("B", actor="t")
        with tenant(self.b.tenant_id):
            self.b_member = add_member(self.b.id, msisdn="0712000009", name="B1", actor="t")

    def counters(self):
        with cross_tenant("test: read both counters", actor="t"):
            return {g.id: g.last_member_sequence for g in Group.objects.filter(pk__in=(self.a.id, self.b.id))}

    def test_a_foreign_group_is_refused_and_nothing_is_written(self):
        before, people = self.counters(), Person.objects.count()
        with tenant(self.a.tenant_id), self.assertRaisesMessage(CommunityError, "Unknown group"):
            add_member(self.b.id, msisdn="0712000001", name="Stranger", actor="t")
        self.assertEqual(self.counters(), before)
        self.assertEqual(Person.objects.count(), people)  # the person rolled back with the join

    def test_a_foreign_membership_is_unknown(self):
        with tenant(self.a.tenant_id):
            for use_case in (lambda: set_title(self.b_member.id, "X", actor="t"),
                             lambda: leave_group(self.b_member.id, actor="t")):
                with self.subTest(use_case), self.assertRaisesMessage(CommunityError, "Unknown member"):
                    use_case()
        with tenant(self.b.tenant_id):
            self.assertEqual(Membership.objects.get(pk=self.b_member.id).status, "active")

    def test_the_database_refuses_a_foreign_group_inside_a_tenant(self):
        from contexts.identity.public import register_person
        person = register_person("0712000001", "X").id
        with tenant(self.a.tenant_id), self.assertRaises(DatabaseError), transaction.atomic():
            Membership.objects.create(group_id=self.b.id, person_id=person, member_code="M02")

    def test_the_database_refuses_a_membership_outside_its_groups_tenant(self):
        from contexts.identity.public import register_person
        person = register_person("0712000001", "X").id
        with cross_tenant("test: write across tenants", actor="t"):
            with self.assertRaisesMessage(DatabaseError, "belongs to its group's tenant"), transaction.atomic():
                Membership.objects.create(group_id=self.b.id, person_id=person, member_code="M02",
                                          tenant_id=self.a.tenant_id)
            ok = Membership.objects.create(group_id=self.b.id, person_id=person, member_code="M02",
                                           tenant_id=self.b.tenant_id)
            self.assertEqual(ok.member_code, "M02")

    def test_no_tenant_context_is_a_tenancy_error(self):
        for use_case in (lambda: add_member(self.a.id, msisdn="0712000001", name="P", actor="t"),
                         lambda: set_title(self.b_member.id, "X", actor="t"),
                         lambda: leave_group(self.b_member.id, actor="t")):
            with self.subTest(use_case), self.assertRaisesMessage(TenancyError, "needs a tenant context"):
                use_case()


class FoundingTests(TestCase):
    def test_a_group_may_exist_without_a_fund_and_open_several(self):
        group = create_group("Welfare circle", actor="t")
        self.enterContext(tenant(group.tenant_id))
        self.assertFalse(Fund.objects.exists())
        names = [open_fund(group.id, name=n, actor="t").name for n in ("Main savings", "Welfare")]
        self.assertEqual(names, ["Main savings", "Welfare"])
        with self.assertRaisesMessage(CommunityError, "already has a fund"):
            open_fund(group.id, name="Welfare", actor="t")
        self.assertIn("fund.opened", [e["action"] for e in history(target_type="fund",
                                                                    target_id=Fund.objects.first().pk)])

    def test_founding_is_refused_inside_a_tenant(self):
        group = create_group("First", actor="t")
        with tenant(group.tenant_id), self.assertRaisesMessage(CommunityError, "outside any tenant"):
            create_group("Nested", actor="t")

    def test_a_group_needs_a_name(self):
        with self.assertRaisesMessage(CommunityError, "needs a name"):
            create_group("   ", actor="t")
