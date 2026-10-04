"""Closing a custodian account, so its fund can close (ADR-0015): only when
the custodian and WEPL's books both show nothing left and nothing is in
question, signed off by two members granted correct_records."""
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, transaction
from django.test import TestCase
from django.utils import timezone

from contexts.communities.public import CommunityError, close_fund
from contexts.custody.application.collections import UnknownAccount, receive
from contexts.custody.infrastructure.models import ExternalAccount, StatementLine
from contexts.custody.public import CustodyError, close_external_account
from contexts.shared_kernel.money import Money
from simulators.custodian_bank import bank
from tests.scenario import Scenario

N = "0012345678901"


class ClosingAnAccountTests(TestCase):
    def setUp(self):
        self.s = Scenario()
        self.wanjiku, self.otieno, self.mutua = self.s.m[0], self.s.m[1], self.s.m[4]

    def close(self, by=None, confirmed_by=None):
        with self.s.acting():
            return close_external_account(self.s.ea.id, by=(by or self.wanjiku).id,
                                      confirmed_by=(confirmed_by or self.otieno).id)

    def pay_everyone_out(self):
        bank.deposit(N, "1000", msisdn=self.mutua.msisdn, name="M")
        self.s.sync()
        bank.withdraw(N, "1000", narration=self.s.approve("1000", charged=self.mutua))
        self.s.sync()

    def test_an_emptied_account_closes_and_then_its_fund_can(self):
        self.pay_everyone_out()
        with self.s.acting(), self.assertRaisesMessage(CommunityError, "linked custodian account that is still open"):
            close_fund(self.s.fund.id, actor="t")
        self.assertFalse(self.close().is_open)
        with self.s.acting():
            self.assertEqual(close_fund(self.s.fund.id, actor="t").status, "closed")

    def test_money_still_at_the_custodian_keeps_it_open(self):
        bank.deposit(N, "1000", msisdn=self.wanjiku.msisdn, name="W")
        self.s.sync()
        with self.assertRaisesMessage(CustodyError, "still reports a balance of 1000.00"):
            self.close()
        with self.s.acting():
            self.assertIsNone(ExternalAccount.objects.get(pk=self.s.ea.id).closed_at)

    def test_money_that_left_without_a_mandate_keeps_it_open_until_explained(self):
        bank.deposit(N, "1000", msisdn=self.wanjiku.msisdn, name="W")
        bank.withdraw(N, "1000", narration="CASH")
        self.s.sync()
        with self.assertRaisesMessage(CustodyError, "1 alert(s) on its lines are still open"):
            self.close()

    def test_it_takes_two_members_granted_correct_records(self):
        for by, confirmed_by in ((self.wanjiku, self.wanjiku), (self.wanjiku, self.s.m[4])):
            with self.subTest(confirmed_by=confirmed_by.code), self.assertRaisesMessage(CustodyError,
                                                                                         "Not authorised"):
                self.close(by, confirmed_by)

    def test_a_closed_account_stays_closed_and_takes_no_new_transaction(self):
        self.pay_everyone_out()
        self.close()
        with self.assertRaisesMessage(CustodyError, "already closed"):
            self.close()
        bank.deposit(N, "50", msisdn=self.wanjiku.msisdn, name="W")
        with self.assertRaisesMessage(CustodyError, "but the custodian reports a new transaction"):
            self.s.sync()
        with self.assertRaises(UnknownAccount):  # the bank's collections calls find no open account
            receive(N, [])
        self.enterContext(self.s.acting())
        account = ExternalAccount.objects.filter(pk=self.s.ea.id)
        line = StatementLine.objects.filter(external_account_id=self.s.ea.id).first()
        for write in (lambda: account.update(closed_at=None), lambda: account.update(closed_at=timezone.now()),
                      lambda: account.update(account_number="0099"), lambda: account.delete(),
                      lambda: StatementLine.objects.create(
                          external_account_id=self.s.ea.id, external_id="X1", sequence=99, posted_at=timezone.now(),
                          kind=line.kind, amount=line.amount)):
            with self.assertRaises(DatabaseError), transaction.atomic():
                write()

    def test_the_nightly_sync_fails_loudly_on_activity_after_closing(self):
        self.pay_everyone_out()
        self.close()
        bank.deposit(N, "50", msisdn=self.wanjiku.msisdn, name="W")
        with self.assertRaisesMessage(CommandError, "was closed on"):
            call_command("sync_accounts", stdout=open("/dev/null", "w"))
        self.assertEqual(self.s.balance_of(self.wanjiku), Money("0"))  # the new line was not taken in
