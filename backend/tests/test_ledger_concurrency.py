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
        from contexts.communities.public import add_member
        with tenant(self.group.tenant_id):
            member_id = add_member(self.group.id, msisdn="0700004242", name="Racer", actor="test").id
        member = self.key(AccountPurpose.MEMBER_INTEREST, member_id=member_id)
        ids = []
        errors = run_together(lambda n: ids.append(resolve(member).pk), self.group.tenant_id)
        self.assertEqual(errors, [])
        self.assertEqual(len(set(ids)), 1)
        with tenant(self.group.tenant_id):
            self.assertEqual(Account.objects.filter(fund_id=self.fund.id, member_id=member_id).count(), 1)

    def test_racing_retries_of_one_reversal_all_get_its_id(self):
        """A retry racing its own first attempt is a replay, not a second
        reversal: PostgreSQL may report the reversal's unique index before the
        key's, and that must still read as "this key already posted"."""
        with tenant(self.group.tenant_id):
            entry = post_journal(self.draft("original"))
        made = []
        errors = run_together(lambda n: made.append(reverse_journal(entry, idempotency_key="the-reversal")),
                              self.group.tenant_id)
        self.assertEqual(errors, [])
        self.assertEqual(len(made), JOINERS)
        self.assertEqual(len(set(made)), 1)
        with tenant(self.group.tenant_id):
            self.assertEqual(JournalEntry.objects.filter(reverses_id=entry).count(), 1)


class TransferRaceTests(unittest.TestCase):
    """A fund transfer is posted once, whatever keys its callers use (ledger
    0010). Before the unique index, 0009's commit-time pair check let two
    concurrent postings of one transfer under different keys both commit."""
    databases = {"default"}

    def setUp(self):
        from contexts.communities.public import add_member
        from contexts.custody.public import link_external_account
        self.group = create_group(f"Transfer races {self._testMethodName}", actor="test")
        with tenant(self.group.tenant_id):
            self.a = open_fund(self.group.id, name="General", actor="test")
            self.b = open_fund(self.group.id, name="Welfare", actor="test")
            self.bank = link_external_account(self.a.id, institution="Custodian Bank", account_number=self._testMethodName[-20:],
                                              account_name="Races", connector="upload", actor="test").id
            self.member = add_member(self.group.id, msisdn="0700004343", name="Owner", actor="test").id
            post_journal(JournalDraft.build(
                idempotency_key="seed", group_id=self.group.id, fund_id=self.a.id, kind="contribution",
                cause_type="t", cause_id="seed", postings=[(self.key(self.a, AccountPurpose.CUSTODY_CASH), Side.DEBIT,
                                                            Money("100")),
                                                           (self.key(self.a, AccountPurpose.MEMBER_INTEREST),
                                                            Side.CREDIT, Money("100"))]))
            for p in (AccountPurpose.CUSTODY_CASH, AccountPurpose.MEMBER_INTEREST):
                resolve(self.key(self.b, p))  # so no writer waits on another's first use of an account

    def key(self, fund, purpose):
        return AccountKey(group_id=self.group.id, fund_id=fund.id, purpose=purpose,
                          member_id=self.member if purpose is AccountPurpose.MEMBER_INTEREST else None,
                          external_account_id=self.bank if purpose is AccountPurpose.CUSTODY_CASH else None)

    def transfer(self, prefix):
        from contexts.ledger.contract import TRANSFER_IN, TRANSFER_OUT, FundTransfer
        D, C, amount = Side.DEBIT, Side.CREDIT, Money("80")
        leg = lambda fund, kind, postings: JournalDraft.build(
            idempotency_key=f"{prefix}:{kind}", group_id=self.group.id, fund_id=fund.id, kind=kind,
            cause_type="governance.fund_transfer", cause_id="1", postings=postings)
        return FundTransfer(
            leg(self.a, TRANSFER_OUT, [(self.key(self.a, AccountPurpose.MEMBER_INTEREST), D, amount),
                                       (self.key(self.a, AccountPurpose.CUSTODY_CASH), C, amount)]),
            leg(self.b, TRANSFER_IN, [(self.key(self.b, AccountPurpose.CUSTODY_CASH), D, amount),
                                      (self.key(self.b, AccountPurpose.MEMBER_INTEREST), C, amount)]))

    def test_one_transfer_under_two_keys_at_once_is_posted_once(self):
        """Both writers post, then hold their transactions open until the other
        has posted too (or cannot, because it waits on the first), so neither
        commit-time check sees the other's legs."""
        import threading
        from contexts.ledger.public import post_transfer
        from django.db import connection
        both_posted, made, errors = threading.Barrier(2), [], []

        def run(n):
            try:
                with tenant(self.group.tenant_id):
                    made.append(post_transfer(self.transfer(f"caller-{n}")))
                    try:
                        both_posted.wait(timeout=3)
                    except threading.BrokenBarrierError:
                        pass  # the other writer is waiting on this one's legs
            except Exception as exc:
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=(n,)) for n in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(made), 1, errors)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], LedgerError)
        self.assertIn("already been posted under another key", str(errors[0]))
        with tenant(self.group.tenant_id):
            self.assertEqual(JournalEntry.objects.filter(cause_id="1").count(), 2)
            self.assertEqual(account_balance(self.key(self.a, AccountPurpose.MEMBER_INTEREST)), Money("20"))

    def test_racing_retries_of_one_transfer_all_get_its_entries(self):
        from contexts.ledger.public import post_transfer
        made = []
        errors = run_together(lambda n: made.append(post_transfer(self.transfer("same"))), self.group.tenant_id)
        self.assertEqual(errors, [])
        self.assertEqual(len(set(made)), 1)
        with tenant(self.group.tenant_id):
            self.assertEqual(JournalEntry.objects.filter(cause_id="1").count(), 2)
            self.assertEqual(account_balance(self.key(self.b, AccountPurpose.MEMBER_INTEREST)), Money("80"))
