"""The ledger's rules hold in PostgreSQL too, whatever code writes to it."""
from django.db import connection, transaction
from django.db.utils import DatabaseError
from django.test import TestCase

from contexts.ledger.contract import AccountKey, AccountPurpose, JournalDraft, LedgerError, Posting, Side
from contexts.ledger.infrastructure.models import Account, JournalEntry, JournalLine
from contexts.ledger.public import (account_balance, fund_position, member_balances, post_journal, reverse_journal,
                                    trial_balance)
from contexts.shared_kernel.money import Money

CASH = AccountKey(1, 1, AccountPurpose.CUSTODY_CASH, external_account_id=9)
MEMBER = AccountKey(1, 1, AccountPurpose.MEMBER_INTEREST, member_id=5)
D, C = Side.DEBIT, Side.CREDIT


def draft(key="k", amount="100"):
    return JournalDraft(idempotency_key=key, group_id=1, fund_id=1, kind="t", cause_type="t", cause_id="1",
                        postings=(Posting(CASH, D, Money(amount)), Posting(MEMBER, C, Money(amount))))


def check_deferred():
    with connection.cursor() as c:
        c.execute("SET CONSTRAINTS ALL IMMEDIATE")
        c.execute("SET CONSTRAINTS ALL DEFERRED")


class PostingTests(TestCase):
    def test_balances_are_derived_by_normal_side(self):
        post_journal(draft())
        self.assertEqual(account_balance(CASH), Money("100"))
        self.assertEqual(member_balances(1), {5: Money("100")})
        self.assertTrue(fund_position(1).invariant_holds)
        self.assertEqual(trial_balance(1), 0)

    def test_same_key_same_entry_is_a_no_op(self):
        self.assertEqual(post_journal(draft("same")), post_journal(draft("same")))
        self.assertEqual(account_balance(CASH), Money("100"))

    def test_same_key_different_entry_is_refused(self):
        post_journal(draft("same", "100"))
        with self.assertRaisesMessage(LedgerError, "different entry"):
            post_journal(draft("same", "101"))

    def test_one_account_per_key_even_with_null_parts(self):
        from contexts.ledger.infrastructure.accounts import resolve
        retained = AccountKey(1, 1, AccountPurpose.RETAINED)
        self.assertEqual(resolve(retained).pk, resolve(retained).pk)
        self.assertEqual(resolve(MEMBER).pk, resolve(MEMBER).pk)

    def test_reversal_restores_balances_once(self):
        entry = post_journal(draft("r"))
        reverse_journal(entry, idempotency_key="r:rev")
        reverse_journal(entry, idempotency_key="r:rev")
        with self.assertRaisesMessage(LedgerError, "already been reversed"):
            reverse_journal(entry, idempotency_key="r:rev2")
        self.assertEqual(account_balance(CASH), Money("0"))
        self.assertEqual(JournalEntry.objects.count(), 2)


class DatabaseRuleTests(TestCase):
    """Writes that bypass the domain on purpose, to prove PostgreSQL refuses them."""

    def setUp(self):
        self.entry = JournalEntry.objects.get(pk=post_journal(draft("base")))
        self.cash, self.member = (Account.objects.get(purpose=p) for p in ("custody_cash", "member_interest"))

    def raw_entry(self, key):
        return JournalEntry.objects.create(idempotency_key=key, fingerprint="", group_id=1, fund_id=1, kind="raw",
                                           cause_type="raw", cause_id="1")

    def test_unbalanced_entry_is_refused_at_commit(self):
        with self.assertRaisesMessage(DatabaseError, "does not balance"):
            with transaction.atomic():
                e = self.raw_entry("raw")
                JournalLine.objects.create(entry=e, account=self.cash, side="D", amount=5)
                JournalLine.objects.create(entry=e, account=self.member, side="C", amount=4)
                check_deferred()

    def test_entry_without_lines_is_refused_at_commit(self):
        with self.assertRaisesMessage(DatabaseError, "at least 2"):
            with transaction.atomic():
                self.raw_entry("empty")
                check_deferred()

    def test_non_positive_amounts_are_refused(self):
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                JournalLine.objects.create(entry=self.entry, account=self.cash, side="D", amount=0)

    def test_history_is_append_only(self):
        line = self.entry.lines.first()
        for action in (lambda: JournalLine.objects.filter(pk=line.pk).update(amount=1),
                       lambda: JournalLine.objects.filter(pk=line.pk).delete(),
                       lambda: JournalEntry.objects.filter(pk=self.entry.pk).update(memo="edited"),
                       lambda: Account.objects.filter(pk=self.cash.pk).update(currency="USD")):
            with self.assertRaisesMessage(DatabaseError, "append-only"):
                with transaction.atomic():
                    action()
