from django.db import IntegrityError, transaction
from django.test import TestCase

from contexts.audit.public import history
from contexts.identity.infrastructure.models import Person
from contexts.identity.public import IdentityError, InvalidMsisdn, correct_person, people, register_person
from contexts.tenancy.public import TenancyError, cross_tenant
from tests.scenario import act_for_new_tenant


class RegistrationTests(TestCase):
    def test_registering_a_number_again_finds_the_same_person_and_keeps_their_name(self):
        first = register_person("0712000001", "Wanjiru Kamau")
        other = register_person("0712000002", "Otieno")
        again = register_person("+254 712 000 001", "Another spelling")
        self.assertEqual(again, first)
        self.assertNotEqual(other.id, first.id)
        self.assertEqual(Person.objects.count(), 2)
        self.assertEqual(Person.objects.get(pk=first.id).display_name, "Wanjiru Kamau")

    def test_the_database_refuses_a_second_person_with_the_same_number(self):
        register_person("0712000001", "A")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Person.objects.create(msisdn="254712000001", display_name="B")

    def test_names_are_cleaned_and_bad_input_registers_nobody(self):
        self.assertEqual(register_person("0712000001", "  Wanjiru   Kamau ").name, "Wanjiru Kamau")
        for name in ("", "   ", None, "x" * 121):
            with self.subTest(name=name), self.assertRaises(IdentityError):
                register_person("0712000002", name)
        with self.assertRaises(InvalidMsisdn):
            register_person("call 0712000003", "C")
        self.assertEqual(Person.objects.count(), 1)

    def test_people_maps_ids_to_people_and_leaves_out_unknown_ids(self):
        a = register_person("0712000001", "A")
        b = register_person("0110000002", "B")
        self.assertEqual(people([a.id, b.id, 999999]), {a.id: a, b.id: b})
        self.assertEqual(people([b.id])[b.id].msisdn, "254110000002")
        self.assertEqual(people([]), {})


class CorrectionTests(TestCase):
    def setUp(self):
        self.person = register_person("0712000001", "Wanjru")

    def correct(self, **kw):
        with cross_tenant("onboarding typo", actor="ops:harry"):
            return correct_person(self.person.id, reason=kw.pop("reason", "typo on the signed form"),
                                  actor="ops:harry", **kw)

    def test_a_correction_changes_the_name_and_number_and_is_audited_with_its_reason(self):
        fixed = self.correct(name="Wanjiru", msisdn="0722000009")
        self.assertEqual((fixed.id, fixed.name, fixed.msisdn), (self.person.id, "Wanjiru", "254722000009"))
        self.assertEqual(register_person("0722000009", "Anyone").id, self.person.id)
        with cross_tenant("read the audit trail", actor="test"):
            [event] = [e for e in history(target_type="person", target_id=self.person.id)
                       if e["action"] == "person.corrected"]
        self.assertEqual(event["data"], {"reason": "typo on the signed form",
                                         "name": {"from": "Wanjru", "to": "Wanjiru"},
                                         "msisdn": {"from": "254712000001", "to": "254722000009"}})

    def test_a_number_that_belongs_to_someone_else_is_refused(self):
        register_person("0722000009", "Someone else")
        with self.assertRaisesMessage(IdentityError, "already belongs to another person"):
            self.correct(msisdn="0722000009")
        self.assertEqual(people([self.person.id])[self.person.id].msisdn, "254712000001")

    def test_a_correction_must_say_why_and_name_a_known_person(self):
        with self.assertRaisesMessage(IdentityError, "say why"):
            self.correct(name="Wanjiru", reason="  ")
        with cross_tenant("x", actor="t"), self.assertRaisesMessage(IdentityError, "Unknown person"):
            correct_person(999999, name="X", reason="r", actor="t")

    def test_a_correction_runs_only_in_a_declared_cross_tenant_operation(self):
        with self.assertRaises(TenancyError):
            correct_person(self.person.id, name="Wanjiru", reason="r", actor="t")
        act_for_new_tenant(self)  # inside one group, the person other groups also see is out of reach
        with self.assertRaises(TenancyError):
            correct_person(self.person.id, name="Wanjiru", reason="r", actor="t")
        self.assertEqual(people([self.person.id])[self.person.id].name, "Wanjru")
