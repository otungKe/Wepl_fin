"""Moving money between a group's funds (ADR-0024): decided like a payout,
booked as two mirrored entries, nothing reaches the bank, and every owner
keeps exactly what they had."""
from django.core.management import call_command
from django.test import TestCase

from contexts.communities.public import CommunityError, close_fund, leave_group, open_fund
from contexts.custody.public import (CustodyError, book_approved_transfers, book_fund_transfer, group_summary, member_pay_ins,
                                     member_statement, reconcile)
from contexts.governance.public import (TransferStatus, decide_fund_transfer, eligible_transfer_approvers,
                                        fund_transfer, propose_fund_transfer)
from contexts.ledger.infrastructure.models import JournalEntry
from contexts.ledger.public import check_books, fund_position, member_balances, trial_balance
from contexts.shared_kernel.money import Money
from simulators.custodian_bank import bank
from tests.scenario import RULES, Scenario

N = "0012345678901"


class FundTransferTests(TestCase):
    def setUp(self):
        self.s = Scenario(rules={**RULES, "interest": "retained"})
        self.main = self.s.fund
        with self.s.acting():
            self.welfare = open_fund(self.s.group.id, name="Welfare", code="WEL", actor="test")
        bank.deposit(N, "6000", msisdn="254712000001", name="WANJIKU K")
        bank.deposit(N, "3000", msisdn="254712000002", name="OTIENO O")
        bank.deposit(N, "1000", msisdn="254712000003", name="AKINYI N")
        bank.deposit(N, "2000", msisdn="254712000004", name="KIPRONO C", reference="WEL")
        self.s.sync()
        self.enterContext(self.s.acting())
        self.m = self.s.m

    def approved(self, amount, *, source="pro_rata", member=None, frm=None, to=None, by=4):
        t = propose_fund_transfer(self.m[by].id, (frm or self.main).id, (to or self.welfare).id, amount=amount,
                                  source=source, member_id=member.id if member else None, reason="Welfare top-up")
        for a in eligible_transfer_approvers(t.id):
            if fund_transfer(t.id).status is not TransferStatus.OPEN:
                break
            decide_fund_transfer(t.id, a.id, approve=True)
        self.assertEqual(fund_transfer(t.id).status, TransferStatus.APPROVED)
        return t

    def held(self, fund, member) -> Money:
        return member_balances(fund.id).get(member.id, Money.zero())

    def totals(self) -> dict:
        return {m.id: self.held(self.main, m) + self.held(self.welfare, m) for m in self.m}

    def assert_sound(self):
        self.assertTrue(reconcile(self.s.ea.id).balanced)
        for fund in (self.main, self.welfare):
            self.assertEqual(trial_balance(fund.id), 0)
            self.assertTrue(fund_position(fund.id).invariant_holds)
        self.assertTrue(all(c.passed for c in check_books()))

    def test_a_pro_rata_transfer_moves_each_member_s_share_and_nobody_s_total_changes(self):
        before = self.totals()
        t = book_fund_transfer(self.approved("1000").id)
        self.assertEqual(t.status, TransferStatus.BOOKED)
        self.assertEqual([self.held(self.main, m) for m in self.m[:3]], [Money("5400"), Money("2700"), Money("900")])
        self.assertEqual([self.held(self.welfare, m) for m in self.m[:4]],
                         [Money("600"), Money("300"), Money("100"), Money("2000")])
        self.assertEqual((fund_position(self.main.id).cash, fund_position(self.welfare.id).cash),
                         (Money("9000"), Money("3000")))
        self.assertEqual(self.totals(), before)
        self.assertEqual(group_summary(self.s.ea.id)["position"].cash, Money("12000"))  # the account did not move
        out, into = JournalEntry.objects.get(pk=t.out_entry_id), JournalEntry.objects.get(pk=t.in_entry_id)
        self.assertEqual((out.kind, out.fund_id, into.kind, into.fund_id),
                         ("fund_transfer_out", self.main.id, "fund_transfer_in", self.welfare.id))
        self.assertEqual(member_statement(self.m[0].id, self.main.id)["lines"][-1]["memo"], "Moved to Welfare")
        self.assertEqual(member_statement(self.m[0].id, self.welfare.id)["lines"][-1]["memo"], "Moved from Main savings")
        self.assert_sound()

    def test_a_transfer_is_not_a_contribution(self):
        book_fund_transfer(self.approved("1000").id)
        self.assertEqual(member_pay_ins(self.welfare.id, self.m[0].id), [])

    def test_one_member_s_own_money_and_they_may_not_approve_it(self):
        t = propose_fund_transfer(self.m[4].id, self.main.id, self.welfare.id, amount="500", source="member",
                                  member_id=self.m[0].id, reason="Move my savings")
        self.assertNotIn(self.m[0].id, {a.id for a in eligible_transfer_approvers(t.id)})
        for a in eligible_transfer_approvers(t.id):
            decide_fund_transfer(t.id, a.id, approve=True)
        book_fund_transfer(t.id)
        self.assertEqual((self.held(self.main, self.m[0]), self.held(self.welfare, self.m[0])),
                         (Money("5500"), Money("500")))
        self.assertEqual(self.held(self.main, self.m[1]), Money("3000"))
        self.assert_sound()

    def test_the_group_s_own_money(self):
        bank.credit_interest(N, "120")  # the constitution keeps interest as the group's (retained)
        self.s.sync()
        before = self.totals()
        book_fund_transfer(self.approved("100", source="retained").id)
        self.assertEqual((fund_position(self.main.id).retained, fund_position(self.welfare.id).retained),
                         (Money("20"), Money("100")))
        self.assertEqual(self.totals(), before)
        self.assert_sound()

    def test_booking_again_changes_nothing(self):
        t = self.approved("1000")
        self.assertEqual(book_approved_transfers(), (1, 0))
        booked = fund_transfer(t.id)
        self.assertEqual(booked.status, TransferStatus.BOOKED)
        entries = JournalEntry.objects.count()
        self.assertEqual(book_fund_transfer(t.id), booked)
        self.assertEqual(JournalEntry.objects.count(), entries)
        self.assertEqual(fund_position(self.welfare.id).cash, Money("3000"))

    def test_only_an_approved_transfer_is_booked(self):
        t = propose_fund_transfer(self.m[4].id, self.main.id, self.welfare.id, amount="100", source="pro_rata",
                                  reason="x")
        with self.assertRaisesMessage(CustodyError, "Only an approved transfer"):
            book_fund_transfer(t.id)

    def test_if_the_money_left_before_booking_the_transfer_fails_and_nothing_moves(self):
        t = self.approved("5000")
        bank.withdraw(N, "6000", narration="NO MANDATE")  # unexplained: the fund's cash drops to 4000
        self.s.sync()
        entries = JournalEntry.objects.count()
        failed = book_fund_transfer(t.id)
        self.assertEqual(failed.status, TransferStatus.FAILED)
        self.assertIn("not already promised", failed.failure)
        self.assertEqual(JournalEntry.objects.count(), entries)
        self.assertEqual(fund_position(self.welfare.id).cash, Money("2000"))

    def test_money_promised_to_a_payout_or_another_transfer_cannot_move(self):
        self.s.approve("8000")  # an issued mandate on the main fund
        from contexts.governance.public import GovernanceError
        with self.assertRaisesMessage(GovernanceError, "only KES 2,000.00 not already promised"):
            propose_fund_transfer(self.m[4].id, self.main.id, self.welfare.id, amount="3000", source="pro_rata",
                                  reason="x")
        self.approved("1500")
        with self.assertRaisesMessage(GovernanceError, "only KES 500.00 not already promised"):
            propose_fund_transfer(self.m[4].id, self.main.id, self.welfare.id, amount="600", source="pro_rata",
                                  reason="x")

    def test_a_leaver_the_group_does_not_spend_keeps_their_money_where_it_is(self):
        bank.deposit(N, "1000", msisdn="254712000005", name="MUTUA M")
        self.s.sync()
        leave_group(self.m[4].id, actor="test")  # the constitution says leavers share no payouts
        t = book_fund_transfer(self.approved("1000", by=3).id)
        self.assertEqual(t.status, TransferStatus.BOOKED)
        self.assertEqual(self.held(self.main, self.m[4]), Money("1000"))
        self.assertEqual(self.held(self.welfare, self.m[4]), Money("0"))
        self.assert_sound()

    def test_a_fund_emptied_by_transfer_can_close_but_not_while_a_transfer_is_pending(self):
        t = self.approved("2000", source="member", member=self.m[3], frm=self.welfare, to=self.main, by=0)
        with self.assertRaises(CommunityError):
            close_fund(self.welfare.id, actor="test")
        book_fund_transfer(t.id)
        self.assertEqual(self.held(self.main, self.m[3]), Money("2000"))
        self.assertEqual(close_fund(self.welfare.id, actor="test").status, "closed")
        self.assert_sound()


class NightlyBookingTests(TestCase):
    def test_the_nightly_run_books_what_each_group_approved(self):
        s = Scenario()
        with s.acting():
            welfare = open_fund(s.group.id, name="Welfare", actor="test")
        bank.deposit(N, "1000", msisdn="254712000001", name="WANJIKU K")
        s.sync()
        with s.acting():
            t = propose_fund_transfer(s.m[4].id, s.fund.id, welfare.id, amount="400", source="pro_rata", reason="x")
            for a in eligible_transfer_approvers(t.id)[:2]:
                decide_fund_transfer(t.id, a.id, approve=True)
        call_command("book_fund_transfers", stdout=open("/dev/null", "w"))
        with s.acting():
            self.assertEqual(fund_transfer(t.id).status, TransferStatus.BOOKED)
            self.assertEqual(fund_position(welfare.id).cash, Money("400"))
