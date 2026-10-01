"""Ledger races settled by PostgreSQL, on real connections that commit.

A plain unittest.TestCase for the reason given in tests/test_concurrency.py:
each test commits in a tenant of its own, and the database, not the
application's early checks, decides the outcome."""
import unittest

from contexts.communities.public import create_group, open_fund
from contexts.ledger.contract import AccountKey, AccountPurpose, JournalDraft, LedgerError, Side
from contexts.ledger.infrastructure.accounts import resolve
from contexts.ledger.infrastructure.models import Account, JournalEntry
from contexts.ledger.public import account_balance, post_journal, reverse_journal
from contexts.shared_kernel.money import Money
from contexts.tenancy.public import tenant
from tests.test_concurrency import JOINERS, run_together


class LedgerRaceTests(unittest.TestCase):
    databases = {"default"}  # so the runner builds the test database even when run alone

    def setUp(self):
        self.group = create_group(f"Ledger races {self._testMethodName}", actor="test")
        with tenant(self.group.tenant_id):
            self.fund = open_fund(self.group.id, name="Main savings", actor="test")

    def key(self, purpose, **kw):
        return AccountKey(group_id=self.group.id, fund_id=self.fund.id, purpose=purpose, **kw)

    def draft(self, idem, amount="100"):
        return JournalDraft.build(
            idempotency_key=idem, group_id=self.group.id, fund_id=self.fund.id, kind="t", cause_type="t",
            cause_id=idem, postings=[(self.key(AccountPurpose.UNEXPLAINED_OUT), Side.DEBIT, Money(amount)),
                                     (self.key(AccountPurpose.RETAINED), Side.CREDIT, Money(amount))])

    def test_racing_reversals_of_one_entry_post_exactly_one(self):
        with tenant(self.group.tenant_id):
            entry = post_journal(self.draft("original"))
        made = []
        errors = run_together(
            lambda n: made.append(reverse_journal(entry, idempotency_key=f"reverse-{n}")), self.group.tenant_id)
        self.assertEqual(len(made), 1)
        self.assertEqual(len(errors), JOINERS - 1)
        for e in errors:
            self.assertIsInstance(e, LedgerError)
            self.assertIn("already been reversed", str(e))
        with tenant(self.group.tenant_id):
            self.assertEqual(list(JournalEntry.objects.filter(reverses_id=entry).values_list("pk", flat=True)), made)
            self.assertEqual(account_balance(self.key(AccountPurpose.RETAINED)), Money("0"))

    def test_racing_posts_with_one_key_post_once_and_all_get_its_id(self):
        made = []
        errors = run_together(lambda n: made.append(post_journal(self.draft("same-key"))), self.group.tenant_id)
        self.assertEqual(errors, [])
        self.assertEqual(len(set(made)), 1)
        with tenant(self.group.tenant_id):
            self.assertEqual(JournalEntry.objects.filter(idempotency_key="same-key").count(), 1)
            self.assertEqual(account_balance(self.key(AccountPurpose.RETAINED)), Money("100"))

    def test_racing_posts_with_one_key_and_different_content_are_refused(self):
        made = []
        errors = run_together(lambda n: made.append(post_journal(self.draft("contested", f"{100 + n}"))),
                              self.group.tenant_id)
        self.assertEqual(len(made), 1)
        self.assertEqual(len(errors), JOINERS - 1)
        for e in errors:
            self.assertIn("different entry", str(e))

    def test_racing_first_use_of_an_account_creates_it_once(self):
        member = self.key(AccountPurpose.MEMBER_INTEREST, member_id=4242)
        ids = []
        errors = run_together(lambda n: ids.append(resolve(member).pk), self.group.tenant_id)
        self.assertEqual(errors, [])
        self.assertEqual(len(set(ids)), 1)
        with tenant(self.group.tenant_id):
            self.assertEqual(Account.objects.filter(fund_id=self.fund.id, member_id=4242).count(), 1)
