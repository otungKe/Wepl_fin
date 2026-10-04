"""A group's payment code (ADR-0018): what members quote, before their member
code, when paying into the pooled collection account."""
from django.db import DatabaseError, connection, transaction
from django.test import TestCase

from contexts.communities.infrastructure.models import Group
from contexts.communities.public import create_group, group_for_payment_code
from contexts.shared_kernel.check_digit import check_digit, is_valid
from contexts.tenancy.public import cross_tenant, tenant


class PaymentCodeTests(TestCase):
    def test_every_group_gets_its_own_readable_code_at_founding(self):
        codes = {create_group(f"G{i}", actor="t").payment_code for i in range(20)}
        self.assertEqual(len(codes), 20)
        for code in codes:
            self.assertRegex(code, r"^[1-9][0-9]{6}$")  # typed on any keypad
            self.assertTrue(is_valid(code))  # its own check digit

    def test_a_code_never_changes(self):
        g = create_group("Umoja", actor="t")
        with tenant(g.tenant_id), self.assertRaisesMessage(DatabaseError, "never changes"), transaction.atomic():
            Group.objects.filter(pk=g.id).update(payment_code="1234566")

    def test_a_code_finds_its_group_only_where_the_caller_may_look(self):
        a, b = create_group("A", actor="t"), create_group("B", actor="t")
        with tenant(a.tenant_id):
            self.assertEqual(group_for_payment_code(a.payment_code).id, a.id)
            self.assertIsNone(group_for_payment_code(b.payment_code))  # another tenant's group is invisible
        with cross_tenant("test: routing", actor="t"):
            self.assertEqual(group_for_payment_code(b.payment_code).id, b.id)

    def test_the_database_and_the_code_agree_on_check_digits(self):
        with connection.cursor() as c:
            for base in ("100000", "123456", "555555", "907612", "999999"):
                c.execute("SELECT communities_damm(%s)", [base])
                self.assertEqual(str(c.fetchone()[0]), check_digit(base))

    def test_the_database_refuses_a_code_with_a_wrong_check_digit(self):
        g = create_group("Umoja", actor="t")
        with tenant(g.tenant_id), self.assertRaisesMessage(DatabaseError, "communities_payment_code_digits"), \
                transaction.atomic(), connection.cursor() as c:
            c.execute("INSERT INTO communities_group (tenant_id, name, last_member_sequence, payment_code, created_at) "
                      "VALUES (%s, 'Copy', 0, '1234567', now())", [g.tenant_id])
