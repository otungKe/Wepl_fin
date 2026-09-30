from decimal import Decimal

from django.db import connection, transaction
from django.db.utils import DatabaseError
from django.test import TestCase

from governance import services as gov
from ledger import services as ledger
from ledger.models import Account, JournalEntry, JournalLine

P = Account.Purpose
D, C = Account.Side.DEBIT, Account.Side.CREDIT


class LedgerTests(TestCase):
    def setUp(self):
        self.group, self.fund = gov.create_group("G", actor="t")
        self.m = gov.add_member(self.group, msisdn="0711111111", name="A", actor="t")
        self.cash = self._acct(P.CUSTODY_CASH, external_account_id=1)
        self.member = self._acct(P.MEMBER_INTEREST, member_id=self.m.pk)

    def _acct(self, purpose, **kw):
        return ledger.account(purpose, group_id=self.group.pk, fund_id=self.fund.pk, **kw)

    def _post(self, key, amount="100.00", lines=None):
        amount = Decimal(amount)
        return ledger.post(idempotency_key=key, group_id=self.group.pk, fund_id=self.fund.pk, kind="test",
                           cause_type="test", cause_id=1, lines=lines or [
                               ledger.Line(self.cash, D, amount), ledger.Line(self.member, C, amount)])

    def _check_deferred(self):
        with connection.cursor() as c:
            c.execute("SET CONSTRAINTS ALL IMMEDIATE")
            c.execute("SET CONSTRAINTS ALL DEFERRED")

    def test_balances_follow_normal_side(self):
        self._post("a", "100.00")
        self.assertEqual(ledger.balance(self.cash), Decimal("100.00"))
        self.assertEqual(ledger.balance(self.member), Decimal("100.00"))
        self.assertEqual(ledger.trial_balance(self.fund.pk), 0)

    def test_posting_is_idempotent(self):
        first = self._post("same")
        second = self._post("same")
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(ledger.balance(self.cash), Decimal("100.00"))

    def test_unbalanced_entry_is_refused_by_code(self):
        with self.assertRaises(ledger.LedgerError):
            self._post("x", lines=[ledger.Line(self.cash, D, Decimal("1")),
                                   ledger.Line(self.member, C, Decimal("2"))])

    def test_account_key_is_unique_even_with_nulls(self):
        again = self._acct(P.MEMBER_INTEREST, member_id=self.m.pk)
        self.assertEqual(again.pk, self.member.pk)
        retained1 = self._acct(P.RETAINED)
        self.assertEqual(self._acct(P.RETAINED).pk, retained1.pk)

    def test_database_rejects_unbalanced_entry_written_directly(self):
        with self.assertRaisesMessage(DatabaseError, "does not balance"):
            with transaction.atomic():
                entry = JournalEntry.objects.create(idempotency_key="raw", group_id=self.group.pk,
                                                    fund_id=self.fund.pk, kind="raw", cause_type="raw",
                                                    cause_id="1")
                JournalLine.objects.create(entry=entry, account=self.cash, side=D, amount=5)
                JournalLine.objects.create(entry=entry, account=self.member, side=C, amount=4)
                self._check_deferred()

    def test_database_rejects_entry_without_lines(self):
        with self.assertRaisesMessage(DatabaseError, "at least 2"):
            with transaction.atomic():
                JournalEntry.objects.create(idempotency_key="empty", group_id=self.group.pk,
                                            fund_id=self.fund.pk, kind="raw", cause_type="raw", cause_id="1")
                self._check_deferred()

    def test_database_rejects_non_positive_amounts(self):
        entry = self._post("p")
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                JournalLine.objects.create(entry=entry, account=self.cash, side=D, amount=0)

    def test_journal_is_append_only(self):
        entry = self._post("imm")
        line = entry.lines.first()
        for action in (lambda: JournalLine.objects.filter(pk=line.pk).update(amount=1),
                       lambda: JournalLine.objects.filter(pk=line.pk).delete(),
                       lambda: JournalEntry.objects.filter(pk=entry.pk).update(memo="edited"),
                       lambda: Account.objects.filter(pk=self.cash.pk).update(currency="USD")):
            with self.assertRaisesMessage(DatabaseError, "append-only"):
                with transaction.atomic():
                    action()

    def test_reversal_restores_balances_and_keeps_history(self):
        entry = self._post("r")
        ledger.reverse(entry, idempotency_key="r:rev")
        ledger.reverse(entry, idempotency_key="r:rev")
        self.assertEqual(ledger.balance(self.cash), 0)
        self.assertEqual(JournalEntry.objects.count(), 2)
