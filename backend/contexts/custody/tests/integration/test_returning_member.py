"""A person who leaves and comes back (ADR-0012). Kiprono was M04, left, and
returned as M06. Everything recorded against M04 stays M04's."""
from django.test import TestCase

from contexts.communities.public import add_member, leave_group
from contexts.custody.infrastructure.models import LineResolution, PayerMapping, StatementLine
from contexts.governance.infrastructure.models import CapabilityChange
from contexts.ledger.infrastructure.models import JournalEntry, JournalLine
from contexts.notifications.infrastructure.models import OutboxEvent
from contexts.custody.public import attribute_payment, group_summary
from contexts.shared_kernel.money import Money
from simulators.im_bank import bank
from tests.scenario import Scenario

N = "0012345678901"
KIPRONO = "254712000004"


class ReturningMemberTests(TestCase):
    def setUp(self):
        self.s = Scenario()
        self.enterContext(self.s.acting())
        self.old = self.s.m[3]
        bank.deposit(N, "1000", msisdn=KIPRONO, name="KIPRONO C", reference=f"{N} M04")
        self.s.sync()
        leave_group(self.old.id, actor="test")
        self.new = add_member(self.s.group.id, msisdn=KIPRONO, name="Kiprono Cheruiyot", actor="test")

    def test_the_new_spell_has_a_new_code_and_the_old_balance_stays_on_the_old_one(self):
        self.assertEqual((self.old.code, self.new.code), ("M04", "M06"))
        self.assertEqual(self.new.person_id, self.old.person_id)
        bank.deposit(N, "200", msisdn=KIPRONO, name="KIPRONO C")
        self.s.sync()
        self.assertEqual(self.s.balance_of(self.old), Money("1000"))
        self.assertEqual(self.s.balance_of(self.new), Money("200"))
        rows = {r["code"]: (r["status"], r["balance"]) for r in group_summary(self.s.ea.id)["members"]}
        self.assertEqual(rows["M04"], ("left", Money("1000").amount))
        self.assertEqual(rows["M06"], ("active", Money("200").amount))
        self.s.assert_sound(self)

    def test_a_payment_quoting_the_old_code_is_held_not_moved(self):
        bank.deposit(N, "300", msisdn=KIPRONO, name="KIPRONO C", reference=f"{N} M04")
        self.s.sync()
        self.assertEqual(self.s.balance_of(self.old), Money("1000"))
        self.assertEqual(self.s.balance_of(self.new), Money("0"))
        self.assertEqual(self.s.assert_sound(self).unattributed, Money("300"))

    def test_a_remembered_payer_moves_to_the_current_spell_only_when_a_person_says_so(self):
        spouse = "254733999999"
        PayerMapping.objects.create(group_id=self.s.group.id, msisdn=spouse, membership_id=self.old.id,
                                    confirmed_by="test")
        bank.deposit(N, "400", msisdn=spouse, name="SPOUSE")
        self.s.sync()
        self.assertEqual(self.s.assert_sound(self).unattributed, Money("400"))  # not credited to the ended spell
        attribute_payment(StatementLine.objects.get(amount=400).pk, self.new.id, by=self.s.m[1].id)
        self.assertEqual(PayerMapping.objects.get(msisdn=spouse).membership_id, self.new.id)
        bank.deposit(N, "100", msisdn=spouse, name="SPOUSE")
        self.s.sync()
        self.assertEqual(self.s.balance_of(self.new), Money("500"))
        self.s.assert_sound(self)


class LeavingRecordsOnlyTheEndOfTheSpellTests(TestCase):
    """Leaving is a membership fact (review H): it posts no money, sends
    nothing, and rewrites no grant. What it means for the balance is the
    constitution's rule (ADR-0014), not leave_group's."""

    def test_leaving_writes_nothing_outside_the_membership_and_its_audit(self):
        s = Scenario()
        with s.acting():
            bank.deposit(N, "1000", msisdn="254712000001", name="WANJIKU K", reference=f"{N} M01")
            s.sync()
            tables = (JournalEntry, JournalLine, LineResolution, OutboxEvent, CapabilityChange, PayerMapping)
            before = {t.__name__: t.objects.count() for t in tables}
            leave_group(s.m[0].id, actor="test")  # a signatory with a balance
            self.assertEqual({t.__name__: t.objects.count() for t in tables}, before)
        self.assertEqual(s.balance_of(s.m[0]), Money("1000"))
        s.assert_sound(self)


class LeaverSharingTests(TestCase):
    """PINNED, NOT DECIDED. Today a member who left stops sharing interest and
    bank charges, and the interest their money earns goes to the others,
    because sharing reads *active* members. Harry has not yet decided whether
    a leaver's unpaid balance should share until it is paid out (ADR-0014,
    open). This test names today's behaviour so the decision changes it
    deliberately, never by accident."""

    def test_a_leavers_balance_is_frozen_today(self):
        s = Scenario()
        self.enterContext(s.acting())
        for m in s.m:
            bank.deposit(N, "1000", msisdn=m.msisdn, name="X")
        s.sync()
        leave_group(s.m[3].id, actor="test")
        bank.credit_interest(N, "100")
        bank.charge(N, "10")
        s.sync()
        self.assertEqual(s.balance_of(s.m[3]), Money("1000"))
        self.assertEqual({s.balance_of(m) for i, m in enumerate(s.m) if i != 3}, {Money("1022.50")})
        s.assert_sound(self)
